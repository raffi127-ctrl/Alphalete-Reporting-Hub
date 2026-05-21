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

## Hub integration

- [ ] **No dashboard.py structural edits** unless Megan explicitly asks ([[feedback-hub-ownership]]).
- [ ] **UX is 7-year-old simple** — one input per concept, auto-derive labels ([[feedback-simple-ux]]).

---

When you finish a report and the checklist is all ✅, say so explicitly with the list. Don't claim "done" without it.
