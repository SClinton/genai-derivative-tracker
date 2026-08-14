# Crawler setup

The crawler queries multiple search backends for mentions of your resources,
then writes unreviewed candidates to `data/candidates.json`. The site shows
them under **Needs review** with Promote / Dismiss buttons — nothing gets
counted in your ledger stats until you promote it.

You don't need all three backends — enable whichever you set up in
`crawler/queries.yaml` under `engines:`.

## Traditional web search

### Option A — Google Programmable Search (Custom Search JSON API)

1. Go to https://console.cloud.google.com/, create (or reuse) a project.
2. Enable the **Custom Search API** for that project.
3. Under **APIs & Services → Credentials**, create an **API key**. This is
   `GOOGLE_CSE_API_KEY`.
4. Go to https://programmablesearchengine.google.com/ and create a new
   search engine, set to **search the entire web**.
5. Copy the **Search engine ID** — this is `GOOGLE_CSE_CX`.

Free tier: 100 queries/day.

### Option B — SerpAPI (Bing + DuckDuckGo)

Microsoft retired the standalone Bing Web Search API in August 2025, so
Bing results are only practically reachable today through a third-party SERP
provider. SerpAPI covers both Bing and DuckDuckGo through one key.

1. Sign up at https://serpapi.com/ and grab your API key from the dashboard.
2. Set it as `SERPAPI_KEY`.
3. In `queries.yaml`, `serpapi_engines` controls which sub-engines run
   (defaults to `bing` and `duckduckgo`).

Free tier is limited (100 searches/month) — each query × each sub-engine
counts as one search, so keep your query list lean or upgrade the plan.

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

### Other AI engines (not wired up yet)

- **ChatGPT / OpenAI**: no public "web search with citations" endpoint
  suitable for this use case as of this writing.
- **Google Gemini**: the Gemini API supports a Google Search grounding tool;
  could be added as a fourth engine in `crawler/engines.py` following the
  same pattern as `search_perplexity()` if you want it — check Google's
  current Gemini API docs for the grounding tool's exact request shape first,
  since these change.
- **Microsoft Copilot**: no public API for this.

## Add the keys as GitHub Actions secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add whichever of these you're using:

- `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`
- `SERPAPI_KEY`
- `PERPLEXITY_API_KEY`

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

## Run it locally instead (optional)

```bash
cd crawler
pip install -r requirements.txt
export GOOGLE_CSE_API_KEY=your_key      # whichever engines you're using
export GOOGLE_CSE_CX=your_cx
export SERPAPI_KEY=your_key
export PERPLEXITY_API_KEY=your_key
python search_and_log.py
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
`conference_search.engines` (defaults to just `google_cse` to keep it
cheap — add more engines deliberately).

**Cost note:** with the default ~35 names across all four categories, this
pass alone is roughly 35× your resource title count per engine enabled per
run. Disable categories you don't need, or trim the `names:` lists, before
scaling up your resource title list.

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
