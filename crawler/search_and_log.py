#!/usr/bin/env python3
"""
GSP Derivative Works Crawler
-----------------------------
Searches the web for mentions/reuse of OWASP GenAI Security Project
resources and writes candidate entries to data/candidates.json for
human review in the ledger app.

This does NOT auto-confirm anything. It only surfaces leads.

Requires:
  GOOGLE_CSE_API_KEY  - Google Programmable Search API key
  GOOGLE_CSE_CX       - Search engine ID (configured to search "the web")

Config:
  crawler/queries.yaml - list of search queries + exclusion domains

Usage:
  python crawler/search_and_log.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

from engines import ENGINES
from translate import translate_text

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "crawler" / "queries.yaml"
DATA_PATH = ROOT / "data" / "candidates.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_existing_candidates():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return []


def save_candidates(candidates):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(candidates, f, indent=2, sort_keys=False)


def domain_of(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def is_excluded(url, excluded_domains):
    d = domain_of(url)
    return any(d == ex or d.endswith("." + ex) for ex in excluded_domains)


def guess_type(url, title, snippet):
    text = f"{url} {title} {snippet}".lower()
    checks = [
        (["conference", "summit", "session", "agenda", "sched.com"], "Conference session"),
        (["podcast", "episode", "spotify.com", "podcasts.apple"], "Podcast"),
        (["training", "course", "curriculum", "bootcamp"], "Training class"),
        (["slideshare", "slides", "deck", "presentation", "webinar"], "Presentation"),
        (["whitepaper", "datasheet", "brochure", "solution brief"], "Marketing document"),
        (["blog", "article", "medium.com", "substack.com", "news"], "Published article"),
    ]
    for keywords, label in checks:
        if any(k in text for k in keywords):
            return label
    return "Other"


def make_candidate_id(url):
    return "c-" + re.sub(r"[^a-z0-9]+", "-", url.lower())[:80].strip("-")


def build_localized_query(title, lang_entry, cfg):
    """Resource titles are searched as-is (quoted) in every language, since
    proper nouns are usually kept in English even in foreign-language
    content. Optionally OR in translated generic modifier terms to also
    catch informal/paraphrased mentions."""
    base = f'"{title}"'
    if cfg.get("translate_modifiers") and lang_entry["code"] != "en":
        modifiers = cfg.get("modifier_terms", [])
        if modifiers:
            translated = [translate_text(m, lang_entry["code"]) for m in modifiers]
            translated = [t for t in translated if t]
            if translated:
                base += " (" + " OR ".join(translated) + ")"
    return base


def run_search(query, engine_name, job_cfg, existing_by_id, excluded_domains,
                default_type=None, extra_fields=None):
    """Runs one query against one engine, filters/dedups hits, and adds new
    candidates to existing_by_id in place. Returns (new_count, dup_count, excluded_count)."""
    engine_fn = ENGINES.get(engine_name)
    if not engine_fn:
        return 0, 0, 0

    try:
        items = engine_fn(query, job_cfg)
    except Exception as e:
        print(f"  ! {engine_name} raised an error: {e}", file=sys.stderr)
        return 0, 0, 0

    new_count = dup_count = excl_count = 0
    for item in items:
        url = item.get("link", "")
        if not url:
            continue
        if is_excluded(url, excluded_domains):
            excl_count += 1
            continue

        cid = make_candidate_id(url)
        if cid in existing_by_id:
            dup_count += 1
            continue

        title = item.get("title", "")
        snippet = item.get("snippet", "")

        candidate = {
            "id": cid,
            "source": "crawler",
            "engine": item.get("engine", engine_name),
            "status": "unreviewed",
            "title": title,
            "type": default_type or guess_type(url, title, snippet),
            "org": domain_of(url),
            "location": url,
            "link": url,
            "snippet": snippet,
            "matchedQuery": query,
            "date": None,
            "attr": "unclear",
            "notes": "Auto-discovered. Needs human review before counting as a confirmed derivative work.",
            "foundAt": datetime.now(timezone.utc).isoformat(),
        }
        if extra_fields:
            candidate.update(extra_fields)

        existing_by_id[cid] = candidate
        new_count += 1

    return new_count, dup_count, excl_count


def main():
    config = load_config()
    resource_titles = config.get("queries", [])
    excluded_domains = [d.lower() for d in config.get("excluded_domains", [])]
    enabled_engines = config.get("engines", ["google_cse"])
    languages = [l for l in config.get("languages", []) if l.get("enabled")]
    if not languages:
        languages = [{"code": "en", "country": "US", "region": "English (default)", "label": "English (US)"}]

    if not resource_titles:
        print("No queries configured in crawler/queries.yaml", file=sys.stderr)
        sys.exit(1)

    unknown = [e for e in enabled_engines if e not in ENGINES]
    if unknown:
        print(f"Unknown engine(s) in queries.yaml: {unknown}. "
              f"Available: {list(ENGINES.keys())}", file=sys.stderr)

    existing = load_existing_candidates()
    existing_by_id = {c["id"]: c for c in existing}
    totals = {"new": 0, "dup": 0, "excl": 0}

    # -----------------------------------------------------------------
    # Pass 1: resource titles × enabled languages × engines
    # -----------------------------------------------------------------
    for title in resource_titles:
        for lang_entry in languages:
            query = build_localized_query(title, lang_entry, config)
            job_cfg = {
                **config,
                "lang": lang_entry["code"],
                "country": lang_entry.get("country"),
                "lang_label": lang_entry.get("label"),
            }
            for engine_name in enabled_engines:
                print(f"[{engine_name}] [{lang_entry['label']}] Searching: {query}")
                n, d, x = run_search(
                    query, engine_name, job_cfg, existing_by_id, excluded_domains,
                    extra_fields={
                        "language": lang_entry["code"],
                        "languageLabel": lang_entry["label"],
                        "region": lang_entry.get("region"),
                        "matchType": "resource",
                    },
                )
                totals["new"] += n; totals["dup"] += d; totals["excl"] += x
                time.sleep(0.4)

    # -----------------------------------------------------------------
    # Pass 2: resource titles × conferences/associations × conference engines
    # -----------------------------------------------------------------
    conf_cfg = config.get("conference_search", {})
    if conf_cfg.get("enabled"):
        conf_engines = conf_cfg.get("engines", ["google_cse"])
        conf_job_cfg = {**config, "results_per_query": conf_cfg.get("results_per_query", 10)}
        categories = conf_cfg.get("categories", {})

        for cat_name, cat_data in categories.items():
            if not cat_data.get("enabled"):
                continue
            default_type = cat_data.get("default_type")
            for conf_name in cat_data.get("names", []):
                for title in resource_titles:
                    query = f'"{title}" "{conf_name}"'
                    for engine_name in conf_engines:
                        print(f"[{engine_name}] [conference:{cat_name}] Searching: {query}")
                        n, d, x = run_search(
                            query, engine_name, conf_job_cfg, existing_by_id, excluded_domains,
                            default_type=default_type,
                            extra_fields={
                                "matchType": "conference",
                                "conferenceCategory": cat_name,
                                "conferenceName": conf_name,
                            },
                        )
                        totals["new"] += n; totals["dup"] += d; totals["excl"] += x
                        time.sleep(0.4)

    all_candidates = list(existing_by_id.values())
    all_candidates.sort(key=lambda c: c.get("foundAt", ""), reverse=True)
    save_candidates(all_candidates)

    print(f"\nDone. {totals['new']} new candidates, {totals['dup']} duplicates skipped, "
          f"{totals['excl']} excluded-domain hits skipped.")
    print(f"Total candidates on file: {len(all_candidates)}")


if __name__ == "__main__":
    main()
