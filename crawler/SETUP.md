# Crawler setup

The crawler queries multiple search backends for mentions of your resources,
then writes unreviewed candidates to `data/candidates.json`. The site shows
them under **Needs review** with Promote / Dismiss buttons — nothing gets
counted in your ledger stats until you promote it.

You don't need both backends — enable whichever you set up in
`crawler/queries.yaml` under `engines:`.

## Traditional web search

### SerpAPI (Google + Bing + DuckDuckGo)

Google's Custom Search JSON API used to be the way to do this, but as of
2025 its free/standard tier only searches domains you explicitly configure
into the search engine, not the open web — it can't do broad, unrestricted
search anymore, which is what this crawler needs. Microsoft also retired the
standalone Bing Web Search API in August 2025. SerpAPI is the practical
route to real Google, Bing, and DuckDuckGo results today, all through one
key.

1. Sign up at https://serpapi.com/ and grab your API key from the dashboard.
2. Set it as `SERPAPI_KEY`.
3. In `queries.yaml`, `serpapi_engines` controls which sub-engines run
   (defaults to `google`, `bing`, and `duckduckgo`).

Free tier is limited (100 searches/month) — each query × each sub-engine
counts as one search, so keep your query list lean, narrow `serpapi_engines`,
or upgrade the plan.

## AI answer engine

### Perplexity API

Perplexity does live web search as part of answering and returns the source
URLs it cited — useful for catching cases where an AI tool is summarizing or
surfacing your content, not just where a page links to it.

1. Get an API key at https://www.perplexity.ai/settings/api.
2. Set it as `PERPLEXITY_API_KEY`.
3. `perplexity_model` in `queries.yaml` defaults to `sonar` — check
   Perplexity's current model list if you want a different one.

This is billed per request — check current pricing before turning it on for
a long query list.

### Parallel.ai Search API

AI-native semantic search (you describe an objective + keywords, not just a
literal keyword match) — catches paraphrased mentions a literal keyword
search might miss. It's also currently the **only** engine here whose
response includes a per-result publish date, which `search_and_log.py`'s
`normalize_date()` reads into the candidate's `date` field (every other
engine leaves it `null`, and the site's Quick add falls back to today's
date when it's missing).

1. Get an API key at https://platform.parallel.ai.
2. Set it as `PARALLEL_API_KEY`.
3. `parallel_mode` in `queries.yaml` defaults to `basic` (`basic`/`advanced`
   are both $0.005/request; `turbo` is $0.001/request but trades some
   accuracy).

**No confirmed free tier** — unlike SerpAPI's 100/month, Parallel is billed
from the first request as far as their pricing docs state (their marketing
page separately claims "up to 80,000 free search requests," which the
pricing docs don't corroborate — check your own dashboard at
platform.parallel.ai rather than trusting either page blindly). At this
project's current scope (18 titles, English only, one request each) that's
18 requests/run, ~72/month, **~$0.36/month** in basic mode — small, but
real money from the start, unlike the other engines here which have an
actual free allowance.

### Other AI engines considered and not wired up

- **ChatGPT / OpenAI**: no public "web search with citations" endpoint
  suitable for this use case as of this writing.
- **Google Gemini**: the Gemini API supports a Google Search grounding tool;
  could be added as a fourth engine in `crawler/engines.py` following the
  same pattern as `search_perplexity()` if you want it — check Google's
  current Gemini API docs for the grounding tool's exact request shape first,
  since these change.
- **Microsoft Copilot**: Microsoft 365 Copilot's actual public APIs (Chat
  API, Search API) only search *your own tenant's* OneDrive/SharePoint
  content — not the open web, so they're not usable here at all. The real
  open-web equivalent is Azure AI Foundry's "Grounding with Bing Search,"
  but it costs $14/1,000 queries with **no free tier**, and requires
  provisioning real Azure infrastructure (a subscription, an AI Foundry
  project, a deployed model, a Bing grounding connection, and OAuth2
  service-principal auth) rather than just an API key — evaluated and
  decided against in favor of Parallel.ai above, which is cheaper, simpler
  to integrate (a single API-key REST call), and adds real capability
  (publish dates) rather than just another SERP-flavored source.

## Add the keys as GitHub Actions secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add whichever of these you're using:

- `SERPAPI_KEY`
- `PERPLEXITY_API_KEY`
- `PARALLEL_API_KEY`

## Edit your queries

Open `crawler/queries.yaml` and replace the example queries with the actual
titles of your OWASP GenAI Security Project resources — exact phrases in
quotes work best. Also set `engines:` to the backends you've configured.

## Run it

- Runs automatically every Monday at 13:00 UTC (edit the cron line in
  `.github/workflows/crawl.yml` to change the schedule).
- To run on demand: repo → **Actions** tab → **Crawl for derivative works**
  → **Run workflow**.
- Each run commits an updated `data/candidates.json` if it found anything
  new. Refresh the site to see new candidates under "Needs review."

## Attribution

After the crawl, `crawler/attribute.py` runs automatically as a second
workflow step and sets each candidate's `derivedFrom` field -- which
specific OWASP GenAI Security Project resource (e.g. "OWASP Top 10 for LLM
Applications 2026") it appears to be reuse of, shown on its card and
carried into the ledger entry's notes when promoted. Defaults to the
generic "OWASP GenAI Security Project" when no specific resource applies
(e.g. it matched a tool/repo like the AIBOM Generator rather than a
published document, or the corpus doesn't currently have that resource).

This is grounded in `crawler/attribute.py`'s `QUERY_TO_RESOURCE_ID` mapping
(which crawler query found the candidate → which corpus `resource_id`),
not a fresh fuzzy search per candidate -- the MCP server's `search_corpus`
does substring-ish matching that produced false positives in testing (a
generic query like "AIBOM Generator" incorrectly matched an unrelated
document). The mapping is reviewed by hand; the actual displayed title
still comes live from the MCP server's `list_resources` every run, so it
won't go stale even though the mapping itself is static. If you add new
queries to `queries.yaml` that should attribute to a specific resource, add
a matching entry to `QUERY_TO_RESOURCE_ID`.

No API key needed -- the OWASP GenAI Security Project MCP server
(`genai-security-advisor-mcp`) is public, no auth required.

## Run it locally instead (optional)

```bash
cd crawler
pip install -r requirements.txt
export SERPAPI_KEY=your_key      # whichever engines you're using
export PERPLEXITY_API_KEY=your_key
export PARALLEL_API_KEY=your_key
python search_and_log.py
python attribute.py
```

## Adding another engine later

Every engine is just a function in `crawler/engines.py` that takes
`(query, config)` and returns a list of `{title, link, snippet}` dicts,
registered in the `ENGINES` dict at the bottom of that file. Nothing else in
`search_and_log.py` needs to change.

## Multilingual / global search

`crawler/queries.yaml` has a `languages:` list covering major European
languages, Japanese, Chinese (Simplified + Traditional), Hindi, Portuguese
(Brazil) and other South American Spanish variants, and other Asian markets
(Korean, Vietnamese, Thai, Indonesian). Each entry has its own `enabled:
true/false` — a small starter set is on by default (English, Spanish,
French, German, Japanese, Chinese Simplified, Hindi, Portuguese-Brazil);
flip on more as you confirm your quota can handle it.

Resource titles are searched as-is (quoted) in every enabled language — most
sites keep proper nouns like your resource titles in English even when the
surrounding article is in another language, so this alone catches a lot.

For paraphrased/informal mentions, set `translate_modifiers: true` and the
crawler will use the Google Cloud Translation API to translate a short list
of generic terms (`modifier_terms:` — "presentation", "training course",
etc.) into each enabled language and OR them into the query. This needs:

1. Enable the **Cloud Translation API** in Google Cloud Console.
2. Create an API key (can reuse the same project as Custom Search, or a
   separate one).
3. Set it as `GOOGLE_TRANSLATE_API_KEY`.

Translations are cached in `data/translation_cache.json` (committed by the
Action) so you're not re-spending quota translating the same static terms
every week.

**Cost note:** each enabled language roughly multiplies your total query
count. Start with the default starter set, check actual API usage after a
run or two, then expand.

## Conference & association discovery

A second, separate search pass in `crawler/search_and_log.py` — controlled
by `conference_search:` in `queries.yaml` — searches each resource title
alongside a curated list of named conferences and associations, grouped
into four categories you can toggle independently:

- `cybersecurity_conferences` — RSA Conference, Black Hat, DEF CON, BSides,
  Infosecurity Europe, OWASP AppSec, Gartner Security & Risk Management
  Summit, and more.
- `ai_conferences` — NeurIPS, ICML, AI Village @ DEF CON, Applied Machine
  Learning Days, and more.
- `vendor_user_conferences` — AWS re:Inforce/re:Invent, Microsoft Ignite,
  Google Cloud Next, Cisco Live, Splunk .conf, Salesforce Dreamforce,
  ServiceNow Knowledge, Palo Alto Networks Ignite, CrowdStrike Fal.Con.
- `training_conferences` — SANS Training, ISC2 Security Congress, ISACA
  Training Week, Black Hat Training.
- `industry_associations` — ISACA, ISC2, Cloud Security Alliance, IAPP,
  IEEE Security and Privacy, ACM CCS.

Edit the `names:` list under any category in `queries.yaml` to add or
remove specific events. This pass does **not** multiply by the languages
list — conference names are proper nouns too, so it runs once per title ×
conference name × whichever engines are listed under
`conference_search.engines` (defaults to `serpapi`, which itself runs one
search per sub-engine in `serpapi_engines` — see the cost note in
`queries.yaml`).

**Cost note:** with the default ~35 names across all four categories, this
pass alone is roughly 35× your resource title count, per SerpAPI sub-engine
enabled, per run. Disable categories you don't need, trim the `names:`
lists, or narrow `serpapi_engines`, before scaling up your resource title
list.

## Video and training-platform discovery

Two more separate passes, controlled by `video_search:` and
`training_platform_search:` in `queries.yaml`, both deliberately scoped to
just the 3 flagship LLM/Agentic Top 10 titles (not all 18 queries in
`queries:`) to control cost:

- **Video** (`video_search`) — searches YouTube (a real SerpAPI engine) and
  Vimeo (no dedicated SerpAPI engine exists, so this is simulated via a
  `site:vimeo.com` Google search through the same `SERPAPI_KEY` — see
  `SITE_SCOPED_SUB_ENGINES` in `crawler/engines.py`). No new credential
  needed. The YouTube integration is implemented against SerpAPI's
  documented behavior but hasn't been exercised against a live API key in
  this environment — check the first real run's results before trusting it
  fully.
- **Training platforms** (`training_platform_search`) — looks for courses
  on Pluralsight, Coursera, Microsoft Learn, CompTIA, and Udemy referencing
  the LLM/Agentic Top 10. One query per title covers all five platforms via
  OR'd `site:` filters in a single search, not five separate ones.

Both reuse `SERPAPI_KEY` — no new secrets required. Add or remove titles
under each section's `titles:` list to change scope.

**Cost note:** combined, these two passes add ~9 searches/run (~36/month
on the weekly schedule) on top of the ~72/month from the main resource-title
pass — bringing total usage to ~108/month, a small accepted overage against
SerpAPI's 100/month free tier. Once the monthly cap is hit, SerpAPI just
rejects further requests for the rest of that month (the crawler logs a
warning and returns no results for those, it doesn't crash) and resumes
automatically next month. Narrow `serpapi_engines` or the `titles:` lists
further, or upgrade the plan, if you'd rather stay strictly under the cap.

## Limitations, honestly

- Search APIs (and Perplexity) index/access what's publicly reachable —
  paywalled articles, private Slack/Discord shares, and members-only
  training platforms won't surface.
- Type and organization are guessed from the URL/snippet and are often
  wrong — that's why everything lands in "Needs review" rather than being
  auto-confirmed.
- This finds *mentions*, not proof of copying — always check the actual
  page before promoting an entry.
- Free tiers are small. If you enable all three engines across a long query
  list on a weekly schedule, check each provider's pricing before you scale
  up the query count.
- Auto-detected content type, language, and conference tags are best-effort
  guesses from the URL/snippet/matched query — verify before promoting.
