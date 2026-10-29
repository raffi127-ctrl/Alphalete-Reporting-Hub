# Rep Knock Breakdown

Raf, Loom + #l10 thread 2026-10-13: a thread per rep in
**#alphalete-sales-knocking-data** (C0C8KBT065D, private), a new picture of that
rep's knocks every hour, reset weekly. Plus: *"if a rep has 3 failed knocks in a
row can we also have it text my Aplayersknocking report"* → iMessage room
**Knocking Chat A-Players**.

## What it posts

| Where | What | When |
|---|---|---|
| Slack, one parent per rep per week (Sunday start) | `*Rep Name* — knocking data · week of Sun 10/11` | first time the rep knocks that week |
| Reply in that rep's thread | spreadsheet-style picture: every knock (newest first), OwnerVille's status colors, GPS OK/FAIL + distance; 3+ fails in a row shaded red. 50 rows per image | hourly :05, Mon–Fri 2–9 PM, Sat 11 AM–6 PM — **only if the rep's numbers moved** since the last post |
| Text → Knocking Chat A-Players | `GPS alert: <Rep> has N knocks in a row that failed GPS (time to time, distances).` + link to the thread | once per streak (a streak that grows stays one text) |

## Source (OwnerVille, Raf's office 11280 — Lucy 1's login)

TeleMapper Leads → **Today's Activity** (`index.cfm?p=88&tmPicker=MM/DD/YYYY`),
campaign RES AT&T (`invD2DClientId=3`).

- Rep list: a two-number badge (`155 / 323`) = knocked that day.
- `&pane=today&pid=<rep id>` → table `#table-dashboard-store`
  (Location · Status · Time · Last Note · All Notes · GPS Verified?). All rows
  are in the HTML, colors inline, so it is one GET per rep (~1.7 s).
- "In a row" = by knock **time**; the HTML is not guaranteed to be in order.

## Run

```
# preview: pulls, draws PNGs to output/rep_knock_breakdown/<day>/<HHMM>/, posts nothing
python -m automations.rep_knock_breakdown.run --dry-run --force
python -m automations.rep_knock_breakdown.run --dry-run --day 2026-10-13 --only Diego

# live (what the LaunchAgent runs)
python -m automations.rep_knock_breakdown.run --send --text
```

`--send` = Slack, `--text` = iMessage; nothing else writes anywhere.
State (thread ts per rep-week, last posted numbers, streaks already texted):
`~/.config/recruiting-report/rep_knock_breakdown_state.json`.

## Deploy (Lucy 1)

1. Lucy has to be a member of #alphalete-sales-knocking-data (private).
2. `lucy update`, then dry run: `lucy rerun rep_knock_breakdown --machine "Lucy 1"`
   (bare = preview). Look at the PNGs.
3. `lucy rerun install_rep_knock_breakdown_agent --machine "Lucy 1"`.

Tests: `python -m unittest automations.rep_knock_breakdown.test_streaks`
