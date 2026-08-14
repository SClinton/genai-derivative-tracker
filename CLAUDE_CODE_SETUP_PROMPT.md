# Claude Code prompt — GSP Derivative Works Tracker setup

Copy everything in the fenced block below and paste it as your first prompt
to Claude Code, run from inside the unzipped `gsp-derivative-tracker/`
folder (`cd` into it first). Fill in the two bracketed values before
sending.

---

```
I have a static web app + crawler in the current directory that I need
pushed to GitHub and configured. Here's what I need, in order:

1. Confirm the current directory contains: index.html, report.html,
   styles.css, data/candidates.json, data/translation_cache.json,
   crawler/ (search_and_log.py, engines.py, translate.py, queries.yaml,
   requirements.txt, SETUP.md), .github/workflows/crawl.yml, README.md.
   If anything is missing, stop and tell me rather than guessing at it.

2. Initialize a git repo here if one doesn't exist, and create a
   .gitignore that excludes __pycache__/, *.pyc, and .DS_Store.

3. Create a new GitHub repository named [REPO_NAME] under my account
   sclinton using the gh CLI (check `gh auth status` first — if I'm not
   authenticated, tell me the exact `gh auth login` command to run and
   wait for me to confirm before continuing). Make it a public repo unless
   I tell you otherwise, since it needs to serve via GitHub Pages on the
   free tier.

4. Commit all files and push to the main branch of that new repo.

5. Enable GitHub Pages on the repo, serving from the main branch root
   directory. Use the gh CLI or the GitHub API — don't just tell me to
   click through the settings UI unless the CLI genuinely can't do it.

6. List out, in your final summary, the exact names of every GitHub
   Actions secret the crawler workflow expects (read them from
   .github/workflows/crawl.yml — don't hardcode a list, the workflow file
   is the source of truth) and tell me clearly that I need to add the
   values myself via `gh secret set <NAME>` or the repo Settings page,
   since you won't have the API keys. Do not ask me for the key values or
   try to set placeholder secrets.

7. Do NOT enable or run the crawl.yml workflow yet — it will fail without
   real secrets. Just confirm it's present under the repo's Actions tab.

8. After pushing, give me:
   - The GitHub Pages URL (should be
     https://sclinton.github.io/[REPO_NAME]/)
   - The repo URL
   - A short checklist of what I still need to do manually (adding
     secrets, editing crawler/queries.yaml with my actual resource
     titles, and enabling the Action on a schedule)

Ask me before doing anything destructive (force-push, deleting an existing
repo with the same name, etc). If a step fails, tell me exactly what
failed and why rather than working around it silently.
```

---

## Before you run this

- Install the GitHub CLI if you don't have it: https://cli.github.com/
- Run `gh auth login` once, interactively, before starting Claude Code —
  it's cleaner than having Claude Code walk you through auth mid-task.
- Pick a repo name and swap it in for `[REPO_NAME]` above (e.g.
  `genai-derivative-tracker`).

## After Claude Code finishes

Follow `crawler/SETUP.md` in the repo to get your API keys and add them as
secrets, then edit `crawler/queries.yaml` with your actual OWASP GenAI
Security Project resource titles before the first real crawl run.
