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
3. **daily_focus retry check** — the 7/1 evening rerun skipped **Colten Wright**
   + **Rafael Hidalgo**'s LAST-WEEK pulls (current-week wrote fine; last-week
   preserved, not blanked). Root cause = fetch_office.py L291 nav waited for
   `wait_until="load"` on 15s → tripped on a slow-AppStream evening. FIXED
   d931162 (domcontentloaded + 30s, matching L167). Both pulled clean on the
   MORNING run, so 4am was never at real risk. Just confirm they're filled
   (incl. last-week) after tomorrow's run.

## TO BUILD (tomorrow, needs a mini test run) — speed up daily_focus
Two wins, same code area:
1. **One AppStream session across captainships.** `--captainship all` re-drives a
   FULL login per captainship (5×), each with the ~10s Cloudflare wait — a big
   chunk of the ~37-min runtime (7/1 rerun). Open the session once in `main()`,
   pass `target_page` into `run_captainship()`. CAUTION: the per-captainship
   re-login also REFRESHES the session, so a naive single-session refactor risks
   captainships 4–5 failing if it goes stale mid-run — so RE-LOGIN on staleness
   (check validity between captainships, re-auth only if dead).
2. **Dedup Rafael Hidalgo.** He's on the Raf, Sahil, Chan Park AND Jose Antonio
   tabs — all office 11280, fetched fresh 4× per run (wasteful + 4× timeout
   exposure). Cache the pull by office_id within a run.
MUST test with a full mini run before it's trusted at 4am — it's a P1 report.
Files: daily_focus.py (`run_captainship` opens session ~L968; `main()` loops
captainships ~L1219). Timeout hardening already done (fetch_office.py L291,
d931162).
