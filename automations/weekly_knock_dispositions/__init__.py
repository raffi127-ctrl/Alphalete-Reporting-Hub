"""Weekly Knock Dispositions — Raf's Sunday board (Loom 2026-08-21).

One PNG per office in a Sunday '#alphalete-sales' thread: per-rep weekly
knock/talk-to productivity for Mon–Sat, joined with the rep's total apps
from the Tableau PRODUCT SALES SUMMARY.

    Rep | Total Talk To's | Avg Talk To's / Day | Total Apps
        | Avg Talk To's per App | First Knock | Last Knock
        | Avg Gap / Day | Total Gap Hours          + OFFICE TOTALS row

Sources (each pulled fresh by this report — no cross-report reuse):
  * Ownerville 'Disposition by Rep' (p=89) with startDate=<Mon>&endDate=<Sat>
    — the week server-side in ONE table, same URL mechanism the daily knocks
    pull uses for a single day.
  * Ownerville Time Tracker (p=510) — gap minutes. Its JSON endpoint is
    single-date only (dateToSearch=), so the week is 6 calls, summed.
  * Tableau DailyRepBDreportpull (PRODUCT SALES SUMMARY 4WK, rep-level) —
    ONE org-wide crosstab serves every office in the run.

Built multi-office from day one (Megan 2026-08-22): offices are config rows
in offices.py — Raf's office ships enabled, adding another is one entry
(canonical ICD name + how to reach its Ownerville view), no code change.
"""
