Update /Users/carloshidalgo/recruiting-report/PUSHING-OPERATIONS-README.md — the
operations README for the pushing fleet. You are the daily 7 PM updater. Work
strictly from evidence:

1. `cd /Users/carloshidalgo/recruiting-report && git pull --rebase origin main`
2. Gather the last 24h:
   - `git log --since="26 hours ago" --format="%h %ad %s" --date=short` — new
     changes touching automations/, deploy/, or the README.
   - The Mini Control - Lucy 2 sheet (id 1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw,
     read via the repo venv: `from automations.recruiting_report import fill;
     fill._client()`): rows queued in the last 26h — note failures, new action
     types, and anything that looks like an incident (REFUSED / GUARD / STOP /
     failed rows). Also note any NEW worksheet tabs on that spreadsheet.
3. Append ONE dated section at the TOP of the "Changelog" (newest first):
   "### <today's date>" with three short bullet groups — New changes; Issues to
   watch next time (only real ones, with the lesson); Sheets/tabs additions.
   If a change caused breakage, ALSO add or extend an entry in
   "## 6. THE CHANGE→BREAKAGE LEDGER" in the same style as the existing ones.
   If nothing happened in a category, write "- none". Never rewrite existing
   sections beyond that; never touch other files.
4. `git add PUSHING-OPERATIONS-README.md && git commit -m "readme: daily 7pm
   update <date>" && git pull --rebase origin main && git push origin HEAD:main`
5. Do NOT queue anything on Lucy's sheet. Do NOT run any push or browser
   automation. This job reads and writes the README only.
