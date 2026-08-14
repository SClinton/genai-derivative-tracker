"""
Pluggable search backends for the crawler.

Each function takes (query, config_dict) and returns a list of normalized
hits: [{ "title": ..., "link": ..., "snippet": ... }, ...]

Engines are enabled/configured in crawler/queries.yaml under `engines:`.
"""

import os
import sys
import time

import requests


# ---------------------------------------------------------------------------
# Google Programmable Search (Custom Search JSON API)
# ---------------------------------------------------------------------------
def search_google_cse(query, cfg):
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_CX")
    if not api_key or not cx:
        print("  ! skipping google_cse: missing GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX", file=sys.stderr)
        return []

    endpoint = "https://www.googleapis.com/customsearch/v1"
    num = cfg.get("results_per_query", 10)
    results, start, fetched = [], 1, 0

    lang = cfg.get("lang")
    country = cfg.get("country")

    while fetched < num:
        params = {"key": api_key, "cx": cx, "q": query, "start": start, "num": min(10, num - fetched)}
        if lang and lang != "en":
            params["lr"] = f"lang_{lang}"
        if country:
            params["gl"] = country.lower()
        resp = requests.get(endpoint, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"  ! google_cse failed ({resp.status_code}) for: {query}", file=sys.stderr)
            break
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        fetched += len(items)
        start += len(items)
        if "nextPage" not in data.get("queries", {}):
            break
        time.sleep(0.4)
    return results


# ---------------------------------------------------------------------------
# SerpAPI (covers Bing, DuckDuckGo, Yahoo, Yandex, etc. via `engine` param)
# Bing's own Web Search API was retired by Microsoft in Aug 2025, so this is
# the practical route to Bing-flavored (and DuckDuckGo) results.
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
        params = {"engine": sub_engine, "q": query, "api_key": api_key, "num": num}
        if cfg.get("lang"):
            params["hl"] = cfg["lang"]
        if cfg.get("country"):
            params["gl"] = cfg["country"].lower()
        resp = requests.get(endpoint, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"  ! serpapi/{sub_engine} failed ({resp.status_code}) for: {query}", file=sys.stderr)
            continue
        data = resp.json()
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
    payload = {
        "model": cfg.get("perplexity_model", "sonar"),
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Search the web for: {query}.{locale_hint} "
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


ENGINES = {
    "google_cse": search_google_cse,
    "serpapi": search_serpapi,
    "perplexity": search_perplexity,
}
