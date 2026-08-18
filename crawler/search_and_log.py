#!/usr/bin/env python3
"""
GSP Derivative Works Crawler
-----------------------------
Searches the web for mentions/reuse of OWASP GenAI Security Project
resources and writes candidate entries to data/candidates.json for
human review in the ledger app.

This does NOT auto-confirm anything. It only surfaces leads.

Requires (whichever engines are enabled in crawler/queries.yaml):
  SERPAPI_KEY          - SerpAPI key (Google + Bing + DuckDuckGo + YouTube)
  PERPLEXITY_API_KEY   - Perplexity API key
  PARALLEL_API_KEY     - Parallel.ai Search API key
  GOOGLE_TRANSLATE_API_KEY - optional, for translate_modifiers

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
REVIEWED_PATH = ROOT / "data" / "reviewed.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_existing_candidates():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return []


def load_reviewed_ids():
    """IDs the site visitor has already decided on -- promoted to their
    ledger, or dismissed -- synced manually via the site's "Sync reviewed
    status" export (Config page) and a commit to data/reviewed.json. The
    ledger and dismissed/promoted state live only in browser localStorage;
    the crawler has no way to see them directly without this file. Returns
    an empty set if nothing's been synced yet (file doesn't exist) or the
    file can't be parsed, rather than failing the whole run over it."""
    if not REVIEWED_PATH.exists():
        return set()
    try:
        with open(REVIEWED_PATH) as f:
            data = json.load(f)
        return set(data.get("promoted", [])) | set(data.get("dismissed", []))
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"  ! could not read data/reviewed.json ({e}) -- treating as empty.", file=sys.stderr)
        return set()


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
    """Each entry in excluded_domains is either a bare domain ("owasp.org",
    matches the whole domain + subdomains) or a domain + path prefix
    ("github.com/genai-security-project", matches only URLs under that
    path) -- lets project-owned channels/orgs on shared platforms
    (YouTube, LinkedIn, GitHub) be excluded without blocking third-party
    content on the same platform, which is what a bare "youtube.com"
    entry would otherwise do."""
    d = domain_of(url)
    path = urlparse(url).path.rstrip("/").lower()

    for ex in excluded_domains:
        if "/" in ex:
            ex_domain, ex_path = ex.split("/", 1)
            ex_path = "/" + ex_path.rstrip("/")
        else:
            ex_domain, ex_path = ex, None

        if d != ex_domain and not d.endswith("." + ex_domain):
            continue
        if ex_path is None or path == ex_path or path.startswith(ex_path + "/"):
            return True

    return False


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


def normalize_date(raw):
    """Accepts a plain "YYYY-MM-DD" or a longer ISO datetime string and
    keeps just the date part; returns None for anything else rather than
    risk storing a malformed value -- the ledger's date fallback (see
    index.html's Quick add) already treats a missing date as "use today",
    so an unparseable date degrading to None is a safe, not silent,
    failure mode."""
    if not raw:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(raw))
    return m.group(1) if m else None


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
    candidates to existing_by_id in place. Returns (new_count, dup_count, excluded_count).
    dup_count covers both "already in candidates.json" and "already
    reviewed" (promoted/dismissed, per data/reviewed.json, read via
    job_cfg["reviewed_ids"] -- same as date_range, injected once into the
    shared config dict in main() so it reaches every pass automatically)
    -- both mean the same thing here: don't re-surface it."""
    engine_fn = ENGINES.get(engine_name)
    if not engine_fn:
        return 0, 0, 0

    try:
        items = engine_fn(query, job_cfg)
    except Exception as e:
        print(f"  ! {engine_name} raised an error: {e}", file=sys.stderr)
        return 0, 0, 0

    reviewed_ids = job_cfg.get("reviewed_ids") or set()
    new_count = dup_count = excl_count = 0
    for item in items:
        url = item.get("link", "")
        if not url:
            continue
        if is_excluded(url, excluded_domains):
            excl_count += 1
            continue

        cid = make_candidate_id(url)
        if cid in existing_by_id or cid in reviewed_ids:
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
            "date": normalize_date(item.get("date")),
            "attr": "unclear",
            "notes": "Auto-discovered. Needs human review before counting as a confirmed derivative work.",
            "foundAt": datetime.now(timezone.utc).isoformat(),
        }
        if extra_fields:
            candidate.update(extra_fields)

        existing_by_id[cid] = candidate
        new_count += 1

    return new_count, dup_count, excl_count


def get_date_range():
    """Reads DATE_FROM/DATE_TO env vars (set from workflow_dispatch inputs
    on a manually-triggered run -- see .github/workflows/crawl.yml; unset
    on the regular scheduled run, which always searches for whatever
    currently exists, no historical restriction). Returns None if neither
    is set, so every job_cfg[.get("date_range")] check downstream stays a
    simple truthiness check."""
    date_from = os.environ.get("DATE_FROM", "").strip()
    date_to = os.environ.get("DATE_TO", "").strip()
    if not date_from and not date_to:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_from or ""):
        date_from = ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_to or ""):
        date_to = ""
    if not date_from and not date_to:
        print("  ! DATE_FROM/DATE_TO set but neither is a valid YYYY-MM-DD date -- ignoring.", file=sys.stderr)
        return None
    return {"from": date_from or None, "to": date_to or None}


def run_titles_pass(pass_name, pass_cfg, config, existing_by_id, excluded_domains, totals):
    """Shared shape for video_search/training_platform_search: a curated,
    usually-shorter title list against a specific serpapi_engines override
    (e.g. youtube/vimeo, or the training-platform site-scoped search),
    with no cross-product against languages or conference names -- unlike
    Pass 1/2, these exist to add a few extra site-scoped sources cheaply
    for the highest-value titles, not to repeat the full resource-title
    sweep for every engine."""
    if not pass_cfg.get("enabled"):
        return
    titles = pass_cfg.get("titles", [])
    job_cfg = {
        **config,
        "results_per_query": pass_cfg.get("results_per_query", 10),
        "serpapi_engines": pass_cfg.get("serpapi_engines", []),
    }
    for title in titles:
        query = f'"{title}"'
        print(f"[serpapi] [{pass_name}] Searching: {query}")
        n, d, x = run_search(
            query, "serpapi", job_cfg, existing_by_id, excluded_domains,
            extra_fields={"matchType": pass_name},
        )
        totals["new"] += n; totals["dup"] += d; totals["excl"] += x
        time.sleep(0.4)


def main():
    config = load_config()
    # Injected once here rather than into each pass's job_cfg individually --
    # every job_cfg downstream is built as {**config, ...}, so this single
    # assignment reaches Pass 1, conference_search, video_search, and
    # training_platform_search automatically.
    config["date_range"] = get_date_range()
    if config["date_range"]:
        print(f"Historical scan: date_range={config['date_range']} "
              f"(hard filter on Google-family search, bucket approximation on YouTube, "
              f"best-effort prompt hint on Perplexity/Parallel -- see engines.py)")
    config["reviewed_ids"] = load_reviewed_ids()
    if config["reviewed_ids"]:
        print(f"Loaded {len(config['reviewed_ids'])} already-reviewed candidate ID(s) "
              f"from data/reviewed.json -- won't re-surface these.")
    resource_titles = config.get("queries", [])
    excluded_domains = [d.lower() for d in config.get("excluded_domains", [])]
    enabled_engines = config.get("engines", ["serpapi"])
    # A language runs only if BOTH its own `enabled` flag AND its region's
    # region_groups switch are true -- lets queries.yaml flip a whole
    # region (e.g. all of Europe) on/off with one line. A region with no
    # entry in region_groups defaults to enabled, so existing configs
    # without a region_groups section keep working unchanged.
    region_groups = config.get("region_groups", {})
    languages = [
        l for l in config.get("languages", [])
        if l.get("enabled") and region_groups.get(l.get("region"), True)
    ]
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
        conf_engines = conf_cfg.get("engines", ["serpapi"])
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

    # -----------------------------------------------------------------
    # Pass 3: video search (YouTube + Vimeo) -- curated flagship titles only
    # -----------------------------------------------------------------
    run_titles_pass("video", config.get("video_search", {}), config, existing_by_id, excluded_domains, totals)

    # -----------------------------------------------------------------
    # Pass 4: training platform course discovery -- same curated titles
    # -----------------------------------------------------------------
    run_titles_pass(
        "training_platform", config.get("training_platform_search", {}),
        config, existing_by_id, excluded_domains, totals,
    )

    # Prunes candidates that were already sitting in candidates.json from a
    # previous run but have since been synced as reviewed (promoted or
    # dismissed) -- the skip in run_search() above only stops *new* hits
    # from being re-added, it doesn't touch what's already on file.
    reviewed_ids = config["reviewed_ids"]
    before_prune = len(existing_by_id)
    all_candidates = [c for c in existing_by_id.values() if c["id"] not in reviewed_ids]
    pruned_count = before_prune - len(all_candidates)

    all_candidates.sort(key=lambda c: c.get("foundAt", ""), reverse=True)
    save_candidates(all_candidates)

    print(f"\nDone. {totals['new']} new candidates, {totals['dup']} duplicates skipped, "
          f"{totals['excl']} excluded-domain hits skipped.")
    if pruned_count:
        print(f"Pruned {pruned_count} already-reviewed candidate(s) from candidates.json.")
    print(f"Total candidates on file: {len(all_candidates)}")


if __name__ == "__main__":
    main()
