# Report Validation Checklist

Run through this list before saying any new report automation is "done." Each item is a single yes/no — if the answer is "no," stop and fix it.

## Runtime

- [ ] **No redundant downloads.** If two sources give the same metric (e.g. an HTTP `.csv` URL AND a UI Crosstab download), keep only the faster one. Call out redundancies the moment you spot them — don't ship them.
- [ ] **No skipped-step logging that runs anyway.** If we log "skipping X" but still run X, fix the order.
- [ ] **Long synchronous waits are justified.** Anything over 30s of sleep / wait — confirm it can't be shorter (e.g. wait-for-element instead of fixed sleep).
- [ ] **HTTP path tried before UI path** whenever possible (HTTP ~1s vs UI ~60-90s per Tableau view).
- [ ] **Cache hits skip re-download.** `--skip-download` flag works for both UI and HTTP sources.

## Data correctness

- [ ] **Every metric in the sheet is wired** — audit each label in the metric-labels dict against the fill function. Missing rows = blank cells = silent gap.
- [ ] **Column lookups by header label, never by index** ([[feedback-no-hardcoded-columns]]).
- [ ] **Owner-name normalization handles Tableau "NAME\n[city, state]" format** + the alias list ([[feedback-alias-list]]).
- [ ] **Terminated-ICD check wired** — the report cross-references the names it fills against the 'Terminated ICDs' tab and alerts the runner about anyone terminated still on it. Add ONE call per run where the full name list is in scope: `from automations.shared import terminated_icds as ti` → `ti.alert_terminated(names, report_label="<this report>")`. Where the report writes a run-manifest, fold the returned flag into the note (advisory — never marks the run failed). Wrap in try/except so the advisory can't break the run. N/A ONLY for pure aggregate/metric reports with no per-person row (daily_metrics, weather, country_metrics, brand_audit, int_wow_penetration, leaders_call). See [[project-report-backlog]] item 8.
- [ ] **Incremental, never destructive** — empty source data = "not yet uploaded," NOT "wipe the cell" ([[feedback-financial-incremental]]).
- [ ] **Preview on Marcellus first** for any new multi-tab automation ([[feedback-preview-marcellus]]).

## Cross-platform

- [ ] **Works on macOS AND Windows** — no hardcoded `.venv/bin/python`, no Mac-only paths, no `%-I` strftime ([[feedback-cross-platform-reports]]).
- [ ] **Uses the bundled Python** (`sys.executable`), not a system path.

## Failure modes

- [ ] **Per-source error isolation** — one download failing doesn't block the rest.
- [ ] **End-of-run gap report** — list every ICD/metric we couldn't fill, with reason ([[opt-section-data-gaps]]).
- [ ] **Access gaps surfaced in review email** ([[feedback-access-gaps-in-review]]).
- [ ] **Run failures email Megan** via the intake-sheet Code.gs ([[project-glitch-email-pending]]).

## Scheduling — the LaunchAgent actually fires

Committing a plist is NOT scheduling it. A standalone LaunchAgent (anything NOT
riding the 4am day-orchestrator batch) needs a one-shot install ON the machine,
and then needs to be watched fire once before you believe it.

- [ ] **The agent is installed on the runner**, not just committed. `deploy/com.alphalete.<name>.plist` in git does nothing until `lucy update` (pull) THEN `lucy rerun install_<name>_agent` runs on that machine. Reports that ride the 4am orchestrator need no install — they're picked up from `schedule_config.json` by the pull alone. Mixed-mode reports are the trap: a report with a morning orchestrator phase AND its own evening agent looks half-scheduled and reads as working.
- [ ] **You watched a real scheduled fire.** The install returning `reloaded ✓` is not proof. The only honest signal is the NEXT scheduled fire landing: a Hub Activity row, or the wrapper's log file (`output/logs/<name>-<date>-<HHMMSS>.log`). Put a reminder on the first fire — don't call it done the same day you install it.
- [ ] **The loaded schedule matches the plist.** `lucy rerun schedule_audit` lists what each timed job is actually set to fire at; `lucy rerun morning_diag --loaded` reads the LIVE launchd job. Reading the plist FILE proves nothing — the mini's launchd caches the timezone and can fire every calendar job +2h ([[project-mini-launchd-drift]]). A freshly installed agent is exactly when this bites.
- [ ] **It reports itself to the Hub** — `hub_publish.publish_done` from the `deploy/*.sh` wrapper (guarded by a `--dry-run` skip) + the `report_id -> card_id` line in `hub_publish._HUB_CARD`; or the module self-reports via `automations.shared.hub_activity.log_completed(CARD_ID, CARD_NAME)`. Without this a clean run is indistinguishable from a silent miss ([[feedback-launchd-reports-must-publish]]).
- [ ] **`daily_runs` on the card matches the number of passes that actually publish.** A card set to 2 with only one pass wired sits amber forever and nobody can tell "half-scheduled" from "still mid-day."

## Hub integration

- [ ] **No dashboard.py structural edits** unless Megan explicitly asks ([[feedback-hub-ownership]]).
- [ ] **UX is 7-year-old simple** — one input per concept, auto-derive labels ([[feedback-simple-ux]]).

---

When you finish a report and the checklist is all ✅, say so explicitly with the list. Don't claim "done" without it.
