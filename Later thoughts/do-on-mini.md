# Do on the mini (when home)

Tasks that need a run/verify **on the mini itself** (Tableau session, live Hub,
or watching output). Started 2026-07-01. Check items off as done; delete when
the list is empty.

---

## ✅ DONE 7/1
- **Deploy** — mini pulled current `main` (latest `713d088`).
- **Carlos PP** — WROTE LIVE 33/33 for WE 6/28. Back on crosstab end-to-end
  (View-Data scrape abandoned — its Summary is scoped to the one selected
  measure). Dry-run + live clean, validated cell-for-cell. Commit `713d088`.
- **Mini-control poller** — reloaded (PID 53972, exit 0); activated `lucy rerun`
  Hub-publish (207eb6f) + `lucy watch_test` (8e0f53d).
- **Card order** — "This week" cards render in scheduler run order
  (daily_rep_breakdown last). Confirmed on laptop.

## Check these two on the NEXT MORNING (4am) run — no action, just eyeball
1. **Running-now badge** — refresh the Hub mid-batch; confirm the pulsing 🔄
   shows on whatever report is executing. If it looks right, tell Claude → he
   wires the ~20–30s auto-refresh (touches dashboard.py, so needs Megan's OK).
   (Nothing's running off-hours, so this can only be seen during a batch.)
2. **Rashad's Daily Metrics** — confirm it posts EARLY (bumped to P1, runs right
   after Raf's `daily_metrics`).
