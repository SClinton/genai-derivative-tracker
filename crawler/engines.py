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
# SerpAPI (covers Google, Bing, DuckDuckGo, Yahoo, Yandex, etc. via `engine`
# param). Google's own Custom Search API was dropped as an engine here: as
# of 2025 its free/standard tier only searches domains you explicitly
# configure, not the open web, so it can't do the broad, unrestricted search
# this crawler needs -- SerpAPI's `google` sub-engine (see serpapi_engines
# in queries.yaml) gives real unrestricted google.com results instead.
# Bing's own Web Search API was also retired by Microsoft in Aug 2025, so
# this is the practical route to Bing-flavored (and DuckDuckGo) results too.
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
    "serpapi": search_serpapi,
    "perplexity": search_perplexity,
}
