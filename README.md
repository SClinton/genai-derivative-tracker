# GSP Derivative Works Ledger

A single-page tool for tracking reuse of OWASP GenAI Security Project materials
(presentations, marketing docs, articles, conference sessions, podcasts, training
classes) outside genai.owasp.org, YouTube, and official social channels.

No build step, no backend — one HTML file. Data is saved in the browser's
local storage, so it persists across visits on the same device/browser but
is **not** shared across devices automatically. Use **Export JSON** regularly
to back up your data, and **Import JSON** to bring it into another browser
or restore a backup.

## Host it on GitHub Pages under sclinton

1. Create a new repo, e.g. `sclinton/genai-derivative-tracker`.
2. Add `index.html` (this file) to the repo root.
3. In the repo: **Settings → Pages → Source → Deploy from a branch**, branch
   `main`, folder `/ (root)`. Save.
4. GitHub will publish it at `https://sclinton.github.io/genai-derivative-tracker/`
   within a minute or two.

Quick command-line version:

```bash
git init
git add index.html README.md
git commit -m "Initial derivative works ledger"
git branch -M main
git remote add origin https://github.com/sclinton/genai-derivative-tracker.git
git push -u origin main
```

Then enable Pages as in step 3 above.

## Pages

- `index.html` — the ledger: log entries, review crawler candidates.
- `report.html` — reporting: mentions per channel, a custom date range, and
  a sortable table with clickable source links. Reads the same local data as
  the ledger (undated entries are excluded from range filtering, since they
  can't be placed on a timeline — set a date on them in the ledger to include
  them here).

## Automated crawler (optional)

`crawler/` contains a script + GitHub Actions workflow that searches the web
weekly for mentions of your GSP resources and writes them to
`data/candidates.json` as **unreviewed candidates**. The site loads that file
automatically and shows them under "Needs review" — nothing counts toward
your ledger stats until you hit **Promote to ledger** (or **Dismiss** to
discard false positives).

See `crawler/SETUP.md` for the 5-minute setup (Google Custom Search API key
+ GitHub Actions secrets), plus sections on multilingual search and
conference/association discovery.

## Repo structure

```
index.html                    the app
report.html                   reporting page (channel summary, date range, table)
styles.css                    shared styles for both pages
data/candidates.json          crawler output (auto-updated by Actions)
data/translation_cache.json   cached translations (auto-updated by Actions)
crawler/search_and_log.py     the crawler script
crawler/engines.py            pluggable search backends (Google, SerpAPI, Perplexity)
crawler/translate.py          Google Cloud Translation API helper
crawler/queries.yaml          your resource titles, languages, conferences — edit this
crawler/requirements.txt      Python deps
crawler/SETUP.md              crawler setup instructions
.github/workflows/crawl.yml   scheduled GitHub Action
```
