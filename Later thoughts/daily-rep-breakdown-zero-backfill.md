# Daily Rep Breakdown — 0-backfill  ✅ RESOLVED 2026-07-01

Parked 2026-06-30 (Megan). **Resolved 2026-07-01.**

**Issue:** rep/day with no activity showed blank, not 0.

**Root cause (the real one):** the 0-fill wiring already existed —
`apply_empty_cell_defaults` runs on the current block (step5_fill_one_owner.py
:846) and the frozen block (daily.py:452, all_days=True). The blanks were a
symptom of a *different* bug: `write_per_day_total_apps_formulas` scanned EVERY
named row — including the frozen LAST WEEK block AND the date-header rows — then
applied the current week's "today" cutoff, clearing last week's Thu–Sun Total
Apps, the weekly SUM, OFFICE TOTALS, and even the date-header row (→ "0").

**Fix (code, 418252d, deployed):** `write_per_day_total_apps_formulas` now uses
`_current_zone_rep_rows` so it never touches the frozen block, header rows, or
office totals. Prevents recurrence.

**Repair (data, one-time):** `output/repair_lastweek_rollout.py` rebuilt the
damaged section on all 28 owner tabs from the surviving breakdown — daily +
weekly Total Apps, 0-fill (both blocks), OFFICE TOTALS sums, TOTAL REPS SOLD /
% ON BOARD, restored date headers, col-C width 545→100px. Previewed on Marcellus
Butler, Megan approved ("looks good"), then rolled out. All 28 tie out.

Note: the frozen block only needs to hold until next Monday's rollover (7/6),
which will freeze a fresh, uncorrupted week on its own now that the code is fixed.
