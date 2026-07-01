# Daily Rep Breakdown — still not backfilling 0s

Parked 2026-06-30 (Megan).

**Issue:** the daily rep breakdown report is still not backfilling 0s where it
should. A rep/day with no activity should show **0**, not blank (per the
fill-but-flag rule + "enter 0% if it's 0").

**When picked up:**
- Check `automations/daily_rep_breakdown`'s fill logic for the 0-backfill path
  (where a no-activity rep/day cell should be written as 0).
- Cross-reference `feedback_fill_but_flag` (sheet_flags.py) and the "enter 0 if
  it's 0" rule — don't reintroduce a blank-it guard.
- Note: the rep-breakdown rollover was hardened 2026-06-16 (commits 6580729,
  c63ff77, b78ec0e) but this 0-fill gap persists — so it's a separate code path.
- Validate by comparing actual cell VALUES cell-for-cell, not just row presence
  (feedback_read_actual_content).
