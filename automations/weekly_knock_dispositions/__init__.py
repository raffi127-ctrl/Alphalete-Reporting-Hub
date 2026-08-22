"""Weekly Knock Dispositions — Raf's Sunday board (Loom 2026-08-21).

One PNG per office, posted into the office's EXISTING Sunday Metrics
thread (Raf 2026-08-22 — "Metrics for: <date>", his in #alphalete-sales):
per-rep weekly knock/talk-to productivity for Mon–Sat, joined with the
rep's total apps from the Tableau PRODUCT SALES SUMMARY.

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

Built multi-office from day one (Megan 2026-08-22): Raf's office ships
enabled; every office already enrolled for the daily Knocks/Time-Gaps board
in its metrics thread is DERIVED from office_metrics' table behind the
offices.INCLUDE_ENROLLED gate — flip it when Raf says take it live and the
enrolled offices (current AND future enrollees) join automatically.
"""
