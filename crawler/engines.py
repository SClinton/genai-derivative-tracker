"""
Pluggable search backends for the crawler.

Each function takes (query, config_dict) and returns a list of normalized
hits: [{ "title": ..., "link": ..., "snippet": ... }, ...]

Engines are enabled/configured in crawler/queries.yaml under `engines:`.
"""

import os
import re
import sys
import time
from datetime import datetime, timezone

import requests


# Fallback bounds when a historical date_range only specifies one side --
# Google's custom date range (tbs=cdr:1,...) needs both cd_min and cd_max,
# so an open-ended "from X onward" or "up to Y" still needs a concrete pair.
# 2020-01-01 predates the OWASP GenAI Security Project's existence, so it's
# a safe stand-in for "no real lower bound."
_EARLIEST_FALLBACK = "2020-01-01"


def _iso_to_us_date(iso):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso or "")
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}" if m else None


def _google_date_range_tbs(date_range):
    """Builds Google's tbs=cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY param
    from an ISO {"from": "YYYY-MM-DD"|None, "to": "YYYY-MM-DD"|None} dict.
    Based on Google's documented custom-date-range search syntax -- not
    verified against a live SerpAPI call in this environment (no API key
    available); confirm the first real historical-scan run's result count
    looks sane before relying on it."""
    if not date_range:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cd_min = _iso_to_us_date(date_range.get("from") or _EARLIEST_FALLBACK)
    cd_max = _iso_to_us_date(date_range.get("to") or today)
    if not cd_min or not cd_max:
        return None
    return f"cdr:1,cd_min:{cd_min},cd_max:{cd_max}"


def _date_range_hint(date_range):
    """Soft, best-effort date restriction for engines with no real
    query-level date filter (Perplexity, Parallel) -- appended as a plain-
    language instruction rather than enforced, so it can be ignored or
    only partially honored by the model. Google-family search gets a real
    hard filter instead (see _google_date_range_tbs)."""
    if not date_range:
        return ""
    frm = date_range.get("from")
    to = date_range.get("to")
    if frm and to:
        return f" Only include results originally published between {frm} and {to}."
    if frm:
        return f" Only include results originally published on or after {frm}."
    if to:
        return f" Only include results originally published on or before {to}."
    return ""


# YouTube's own search has no arbitrary custom date range like Google's
# tbs=cdr -- only these fixed relative "upload date" buckets, passed via
# SerpAPI's `sp` param. Only "today" (EgIIAg==) and "this week" (EgIIAw==)
# are corroborated by an independent source beyond SerpAPI's own docs
# (which document only the sort-by-date value, CAI=, not these filter
# presets at all); "this month" and "this year" are extrapolated from the
# same incrementing pattern (...Ag==, ...Aw==, ...BA==, ...BQ==) and not
# independently verified -- confirm the first real historical-scan run's
# result count looks sane before trusting it.
_YOUTUBE_UPLOAD_DATE_SP = {
    "week": "EgIIAw==",
    "month": "EgIIBA==",
    "year": "EgIIBQ==",
}


def _youtube_date_sp(date_range):
    """Approximates a historical date_range as the narrowest YouTube
    upload-date bucket that fully covers it, using only the `from` bound
    (the buckets are all "since N ago", there's no upper-bound concept to
    match `to` against). Deliberately returns None -- no filter, not a
    wrong one -- when the requested range starts further back than
    YouTube's broadest bucket (~1 year): restricting to "this year" would
    silently exclude genuinely older content the historical scan is
    explicitly looking for, which is worse than not filtering at all.
    "Last hour"/"Today" are omitted entirely -- irrelevant for a
    backward-looking historical scan, which is the only thing this
    approximation is for."""
    if not date_range:
        return None
    frm = date_range.get("from")
    if not frm:
        return None
    try:
        from_dt = datetime.strptime(frm, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    days_back = (datetime.now(timezone.utc) - from_dt).days
    if days_back <= 7:
        return _YOUTUBE_UPLOAD_DATE_SP["week"]
    if days_back <= 31:
        return _YOUTUBE_UPLOAD_DATE_SP["month"]
    if days_back <= 365:
        return _YOUTUBE_UPLOAD_DATE_SP["year"]
    return None


# Vimeo and the training platforms have no dedicated SerpAPI engine (unlike
# YouTube, which is a real SerpAPI engine below) -- simulated instead via a
# site:-scoped Google search through the same SERPAPI_KEY, so no new
# credential is needed. Training platforms are OR'd into ONE query per
# title rather than one query per platform, since that's a single search
# either way -- 5x cheaper than querying each site separately.
SITE_SCOPED_SUB_ENGINES = {
    "vimeo": "site:vimeo.com",
    "training_platforms": (
        "(site:pluralsight.com OR site:coursera.org OR site:learn.microsoft.com "
        "OR site:comptia.org OR site:udemy.com)"
    ),
}


# ---------------------------------------------------------------------------
# SerpAPI (covers Google, Bing, DuckDuckGo, YouTube, and the site-scoped
# pseudo-engines above via `engine` param). Google's own Custom Search API
# was dropped as an engine here: as of 2025 its free/standard tier only
# searches domains you explicitly configure, not the open web, so it can't
# do the broad, unrestricted search this crawler needs -- SerpAPI's
# `google` sub-engine (see serpapi_engines in queries.yaml) gives real
# unrestricted google.com results instead. Bing's own Web Search API was
# also retired by Microsoft in Aug 2025, so this is the practical route to
# Bing-flavored (and DuckDuckGo) results too.
# ---------------------------------------------------------------------------
def search_serpapi(query, cfg):
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        print("  ! skipping serpapi: missing SERPAPI_KEY", file=sys.stderr)
        return []

    endpoint = "https://serpapi.com/search"
    sub_engines = cfg.get("serpapi_engines", ["bing", "duckduckgo"])
    num = cfg.get("results_per_query", 10)
    results = []

    for sub_engine in sub_engines:
        site_filter = SITE_SCOPED_SUB_ENGINES.get(sub_engine)
        actual_engine = "google" if site_filter else sub_engine
        search_query = f"{query} {site_filter}" if site_filter else query

        params = {"engine": actual_engine, "api_key": api_key, "num": num}
        # YouTube's SerpAPI engine takes the query as `search_query`, not
        # `q` -- everything else (google/bing/duckduckgo, and the
        # site-scoped pseudo-engines above, which are really `google`
        # underneath) uses `q`. Based on SerpAPI's documented YouTube
        # engine behavior -- not verified against a live call (no API key
        # available in this environment) -- confirm the first real run's
        # output looks right before relying on it.
        if actual_engine == "youtube":
            params["search_query"] = search_query
        else:
            params["q"] = search_query
        if cfg.get("lang") and cfg["lang"] != "en":
            params["hl"] = cfg["lang"]
        if cfg.get("country"):
            params["gl"] = cfg["country"].lower()
        # Real query-level date filter -- for actual Google search (also
        # covers the vimeo/training_platforms pseudo-engines, which route
        # through google underneath) this is a precise custom range.
        # YouTube gets a coarser bucket approximation instead -- see
        # _youtube_date_sp() for why (no arbitrary range support there).
        if actual_engine == "google":
            tbs = _google_date_range_tbs(cfg.get("date_range"))
            if tbs:
                params["tbs"] = tbs
        elif actual_engine == "youtube":
            sp = _youtube_date_sp(cfg.get("date_range"))
            if sp:
                params["sp"] = sp
        resp = requests.get(endpoint, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"  ! serpapi/{sub_engine} failed ({resp.status_code}) for: {query}", file=sys.stderr)
            continue
        data = resp.json()

        if actual_engine == "youtube":
            items = data.get("video_results", [])
            for item in items:
                channel = item.get("channel") or {}
                results.append({
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("description") or channel.get("name", ""),
                    "engine": sub_engine,
                })
        else:
            items = data.get("organic_results", [])
            for item in items:
                results.append({
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "engine": sub_engine,
                })
        time.sleep(0.4)
    return results


# ---------------------------------------------------------------------------
# Perplexity API — an AI answer engine that does live web search and returns
# citations. Useful for catching where an AI tool itself is surfacing/
# summarizing your content, not just where a page links to it.
# ---------------------------------------------------------------------------
def search_perplexity(query, cfg):
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        print("  ! skipping perplexity: missing PERPLEXITY_API_KEY", file=sys.stderr)
        return []

    endpoint = "https://api.perplexity.ai/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    lang_label = cfg.get("lang_label", "")
    locale_hint = f" Prioritize results written in {lang_label}." if lang_label and lang_label != "English (US)" else ""
    date_hint = _date_range_hint(cfg.get("date_range"))
    payload = {
        "model": cfg.get("perplexity_model", "sonar"),
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Search the web for: {query}.{locale_hint}{date_hint} "
                    "List the distinct source URLs you find that are relevant, "
                    "one per line, with a short description of each."
                ),
            }
        ],
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"  ! perplexity failed ({resp.status_code}) for: {query}", file=sys.stderr)
        return []

    data = resp.json()
    citations = data.get("citations", []) or []
    answer_text = ""
    try:
        answer_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        pass

    results = []
    for url in citations:
        results.append({
            "title": "",   # Perplexity returns citation URLs without titles
            "link": url,
            "snippet": answer_text[:300] if answer_text else "",
            "engine": "perplexity",
        })
    return results


# ---------------------------------------------------------------------------
# Parallel.ai Search API -- AI-native semantic search (an "objective" plus
# keywords, not a raw keyword SERP), used alongside SerpAPI/Perplexity to
# catch paraphrased mentions a literal keyword search might miss. Also the
# only engine here whose response includes a per-result publish date --
# search_and_log.py's normalize_date() reads it into the candidate's date
# field, which every other engine leaves None (falling back to "today" at
# Quick-add time -- see index.html).
#
# No confirmed free tier as of this writing (unlike SerpAPI's 100/month) --
# billed per request from the first call. See crawler/SETUP.md for the
# actual cost at this project's current query volume.
# ---------------------------------------------------------------------------
def search_parallel(query, cfg):
    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        print("  ! skipping parallel: missing PARALLEL_API_KEY", file=sys.stderr)
        return []

    endpoint = "https://api.parallel.ai/v1/search"
    date_hint = _date_range_hint(cfg.get("date_range"))
    payload = {
        "objective": f"Find web pages that reuse, cite, or appear derived from: {query}.{date_hint}",
        "search_queries": [query],
        "mode": cfg.get("parallel_mode", "basic"),
    }
    resp = requests.post(
        endpoint,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  ! parallel failed ({resp.status_code}) for: {query}", file=sys.stderr)
        return []

    data = resp.json()
    results = []
    for item in data.get("results", []):
        excerpts = item.get("excerpts") or []
        results.append({
            "title": item.get("title", ""),
            "link": item.get("url", ""),
            "snippet": excerpts[0] if excerpts else "",
            "date": item.get("publish_date"),
            "engine": "parallel",
        })
    return results


ENGINES = {
    "serpapi": search_serpapi,
    "perplexity": search_perplexity,
    "parallel": search_parallel,
}
