#!/usr/bin/env python3
"""
Enriches data/candidates.json with a `derivedFrom` field identifying which
OWASP GenAI Security Project resource (or the project generically) each
candidate appears to be reuse of.

Grounded in matchedQuery (which crawler query in queries.yaml found this
candidate) rather than a fresh fuzzy search against the corpus for every
candidate: the MCP server's search_corpus does substring-ish matching
that's prone to false positives on short/generic terms -- verified live,
"AIBOM Generator" incorrectly matched the LLM Top 10 document. A static,
hand-reviewed mapping from our own curated queries to a specific corpus
resource_id is safer than trusting a live fuzzy match per candidate.

The MCP server is still the source of truth for content: this script
calls list_resources every run and only attributes a candidate to a
specific resource if that resource_id is still present in the live
corpus right now, falling back to the generic project attribution
otherwise -- e.g. if a resource is renamed or retired, or (several of our
queries target tools/repos like the AIBOM Generator and FinBot, not
published documents) was never in the corpus MANIFEST to begin with.

Run as a separate step after search_and_log.py, not folded into it, so a
transient MCP server failure can't also block/corrupt the actual crawl.

Usage:
  python crawler/attribute.py
"""

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "candidates.json"
MCP_URL = "https://genai-security-advisor-mcp.genai-security-advisor-mcp.workers.dev/mcp"
DEFAULT_ATTRIBUTION = "OWASP GenAI Security Project"

# Keyed by matchedQuery with all `"` characters collapsed to a single space
# and whitespace normalized (see normalize()) -- matchedQuery is built by
# double-wrapping an already-quoted crawler query (see
# UMC... er, crawler/search_and_log.py's build_localized_query()), so exact
# quote placement isn't reliable to match on directly. Reviewed by hand
# against the live corpus on 2026-08-17 (see list_resources). Queries with
# no entry here fall back to DEFAULT_ATTRIBUTION.
QUERY_TO_RESOURCE_ID = {
    "OWASP Top 10 for LLM Applications -site:owasp.org": "llm-top10-2026",
    "OWASP GenAI LLM Top 10": "llm-top10-2026",
    "OWASP Top 10 for Agentic Applications": "agentic-top10-2026",
    "OWASP GenAI Data Security Risks and Mitigations": "dsgai-risk-doc-2026",
    "A Practical Guide for Secure MCP Server Development": "mcp-server-development-guide-1.0",
    "A Practical Guide for Securely Using Third-Party MCP Servers": "mcp-third-party-cheatsheet-1.0",
    "OWASP GenAI Security Project Threat Defense COMPASS": "compass-runbook-1.0",
    "State of Agentic AI Security and Governance": "state-of-agentic-ai-security-governance-2.01",
    "OWASP Vendor Evaluation Criteria AI Red Teaming": "red-teaming-vendor-evaluation-criteria-1.0",
    # Deliberately unmapped -> generic DEFAULT_ATTRIBUTION:
    #   "OWASP Top 10 for LLM Applications 2023" -- targets a superseded
    #     version; list_resources defaults to status:"current" and doesn't
    #     surface it.
    #   "AI Security Solutions Landscape ..." (both variants), "OWASP Guide
    #     to Preparing and Responding to Deepfake Events", "OWASP GenAI
    #     Exploit Round-up Report", "OWASP Gen AI Agentic Security Top 10
    #     presentation" -- not in the corpus MANIFEST as of this writing.
    #   "OWASP AIBOM Generator", "FinBot Capture The Flag OWASP", "GenAI
    #     Security Advisor OWASP" -- these are tools/repos, not published
    #     documents, so they're outside the corpus this server indexes.
}


def normalize(matched_query):
    text = re.sub(r'"+', " ", matched_query or "")
    return re.sub(r"\s+", " ", text).strip()


def mcp_call(method, params):
    resp = requests.post(
        MCP_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def fetch_live_resources():
    """Returns {resource_id: title} for the corpus's current resources."""
    result = mcp_call("tools/call", {"name": "list_resources", "arguments": {}})
    payload = json.loads(result["content"][0]["text"])
    return {r["id"]: r["title"] for r in payload.get("resources", [])}


def main():
    if not DATA_PATH.exists():
        print("No data/candidates.json to attribute.", file=sys.stderr)
        return

    with open(DATA_PATH) as f:
        candidates = json.load(f)

    try:
        live_resources = fetch_live_resources()
    except Exception as e:
        print(f"Could not reach the OWASP GenAI Security Project MCP server ({e}) -- "
              f"leaving derivedFrom as-is for this run.", file=sys.stderr)
        return

    changed = 0
    unmapped_queries = set()
    for c in candidates:
        resource_id = QUERY_TO_RESOURCE_ID.get(normalize(c.get("matchedQuery", "")))
        if resource_id and resource_id in live_resources:
            new_value = live_resources[resource_id]
        else:
            if c.get("matchedQuery") and not resource_id:
                unmapped_queries.add(normalize(c["matchedQuery"]))
            new_value = DEFAULT_ATTRIBUTION

        if c.get("derivedFrom") != new_value:
            c["derivedFrom"] = new_value
            changed += 1

    with open(DATA_PATH, "w") as f:
        json.dump(candidates, f, indent=2, sort_keys=False)
        f.write("\n")

    print(f"Attribution: {changed} candidate(s) updated, {len(candidates)} total.")
    if unmapped_queries:
        print("Queries with no specific corpus resource (defaulted to "
              f'"{DEFAULT_ATTRIBUTION}"): {sorted(unmapped_queries)}', file=sys.stderr)


if __name__ == "__main__":
    main()
