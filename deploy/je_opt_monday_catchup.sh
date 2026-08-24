#!/bin/bash
# Monday 3:00pm CST — Just Energy OPT catch-up for the ALPHALETE ORG SHEET, on
# the always-on Mac mini via launchd (com.alphalete.je-opt-monday-catchup).
#
# WHY (Eve 2026-08-24, from the stale-source thread
# drop-tableau-stale-justenergyrtl-salesstaffingproductivityworkbook-jeallretaile):
# the JE OPT section fills a week that runs MONDAY–SUNDAY, and
# alphalete_org_focus runs on MONDAYS ONLY (cadence.weekdays [0]) at ~07:2x. Just
# Energy's Tableau publishes ~1 day behind — observed 1:53pm (2026-07-05, and the
# reason board_catchup.sh exists at 14:30) — so at 07:2x the just-closed SUNDAY is
# not in the view yet. Measured 2026-08-24 on the export itself: WE 8/23 pulled
# that morning stopped at Saturday 8/22, while the already-closed WE 8/16 and
# WE 8/09 both carried all seven days. Sunday is not a small day either: 842 and
# 988 of 'Total Sales Agg' on those two weeks, ~20% of the week each.
#
# And nothing came back for it. opt_je writes the WE column once, on Monday, and
# the org focus does not run again until the following Monday — by which time
# _current_target_week_end() points at the NEXT week's column. So every JE week
# was being finalized a Sunday short.
#
# THE WINDOW IS MONDAY AFTERNOON, and it is narrow at both ends:
#   * after ~13:53, or Sunday still isn't published (that is the whole bug);
#   * before TUESDAY, because the Org Sales Board's reporting week rolls on
#     Tuesday (org_sales_board/week.py reporting_monday: "last week's Monday on a
#     Monday; this week's Monday Tue–Sun"). Eve's constraint, 2026-08-24: run it
#     after the roll and it writes into a day of the NEW week that does not
#     correspond. board_catchup.sh already lives on the same rule — "on MONDAY it
#     also grabs the just-closed SUNDAY before TUESDAY's rollover freezes the
#     week".
# 15:00 sits after JE publishes AND after board_catchup's 14:30, so the two
# afternoon jobs never contend for a Tableau session.
#
# NO --week ARGUMENT ON PURPOSE: on a Monday, opt_je's own
# _current_target_week_end() (opt_nds.py) already returns the Sunday that just
# closed — verified 2026-08-24: Mon 8/24 -> WE 8/23, col '8/23/26'. Passing a
# hand-computed date from bash would be a second source of truth that can drift.
# To back-fill an OLDER week by hand, the module still takes it:
#   python -m automations.alphalete_org_report.opt_je --week 2026-08-16
#
# SAFE / IDEMPOTENT: opt_je writes label-anchored cells (row by col-B label, week
# by date header — never fixed indices), re-writes the SAME week column it wrote
# in the morning, and a listed store with no production is written 0. Running it
# twice writes the same numbers.
#
# TIME KNOB: the hour lives in com.alphalete.je-opt-monday-catchup.plist
# (StartCalendarInterval Hour). 15 = 3pm CST (the mini is Central).
#
# Manual test without writing:  bash deploy/je_opt_monday_catchup.sh --dry-run
# (passes through to the module; --dry-run is appended and wins.)
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/je-opt-monday-catchup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] JE OPT Monday catch-up starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.alphalete_org_report.opt_je "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] JE OPT Monday catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"JE OPT Monday catch-up failed (exit $ST) — check the log; the Tableau login may have expired\" with title \"JE OPT catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
