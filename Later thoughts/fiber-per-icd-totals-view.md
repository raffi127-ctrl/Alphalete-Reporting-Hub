# Fiber Lead Performance — per-ICD totals view added

Megan 2026-05-22: the Fiber Lead Performance dashboard at
https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/FiberLeadPerformance/a79fd021-3606-4aa2-bf55-bc3856cdac99/AUTOMATIONPULL-NICHURNVIEW?:iid=1
now exposes a per-ICD totals worksheet in the Crosstab download dialog.

Context: Raf's Focus Report Fiber pull currently scrapes per-ICD via
View Data (the old workbook had no totals worksheet). With this new
worksheet, the pull can switch to a single Crosstab download covering
all ICDs at once — one request instead of N.

When picking this up:
- Confirm the new worksheet name in the Crosstab dialog (Megan didn't
  share the exact name).
- The custom view `AUTOMATIONPULL-NICHURNVIEW` already filters to the
  data we want; the totals worksheet should expose the per-ICD rollup
  with the same filter applied.
- Currently lives in `automations/recruiting_report/opt_phase.py` Fiber
  scrape path.
