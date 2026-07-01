# Do on the mini (when home)

Tasks that need a run/verify **on the mini itself** (Tableau session, live Hub,
or watching output). Started 2026-07-01. Check items off as done; delete when
the list is empty.

---

## 1. Deploy the latest code
The queued `lucy update` may have already pulled it — confirm at the mini:
```
cd ~/recruiting-report && git pull --ff-only && git log --oneline -4
```
Should include: Carlos PP scrape `973de88`, running-badge `be7a680`,
Hub reorder `fed8933`, Rashad P1 `c07408e`.

## 2. Carlos PP — View-Data scrape test  ← blocks the PP fix
PP has been stale since 5/20 (crosstab flyout won't open). Rewired to a
View-Data scrape; needs one live run to confirm the click position + column
names. **Read-only** (no Sheet writes):
```
PYTHONPATH=. .venv/bin/python -m automations.recruiting_report.opt_phase_carlos --test-view personal_production
```
Then paste the `COLUMNS: [...]` + sample rows to Claude. Claude will:
- tune `PP_ACTIVATE_XY` if it prints **0 rows / no worksheet**,
- fix `PP_PRODUCT_LABELS` if Tableau names the product columns differently,
- then `--apply-view personal_production --dry-run` to verify "3 NI / 2 NL"
  before it goes live.

## 3. Running-now badge — verify, then Claude adds auto-refresh
After the deploy, **refresh the Hub** and confirm the pulsing 🔄 shows on a
report that's currently running (schedule "This week" view). Tell Claude →
Claude wires the auto-refresh so the view updates itself every ~20–30s while
something is running (no manual refresh).

## 4. Eyeball only (should be automatic once deployed)
- ✅ "This week" cards render in **scheduler run order** — CONFIRMED 7/1 (Megan,
  on laptop). daily_rep_breakdown dead last.
- **Rashad's Daily Metrics** posts EARLY next run — bumped to P1, runs right
  after Raf's `daily_metrics`. (verify on the next morning run)

## 5. Restart the mini-control poller  ← activates recent lucy changes
Two changes to `mini_control.py` itself need the poller reloaded (a running
`--loop` won't see new code). One restart activates BOTH:
- `lucy rerun` publishing INCOMPLETE (ran-with-a-note) reports to the Hub
  (207eb6f) — so manual reruns mark the card like the orchestrator does.
- the `lucy watch_test` action (8e0f53d) — fires appstream_watch's test ping.
```
launchctl bootout gui/$(id -u)/com.alphalete.mini-control 2>/dev/null; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphalete.mini-control.plist
```
Then confirm it's alive: `launchctl list | grep mini-control` (PID + exit 0).
Not urgent — today's runs were backfilled to the Hub manually; the
orchestrator half is already live on the next 4am run.
