#!/bin/bash
# ATT B2B Order Log -> "Lucy At&t Order Log" tab on the Vantura Master Sales Board.
#
# Carlos's ATT counterpart to the BOX Order Log (requested 2026-07-19). Pulls
# the ATTTRACKER-B2B ORDERLOG crosstab, un-pivots the per-measure row fan-out
# into one row per real sale, filters to Carlos, and rewrites the log with the
# rep/period dropdowns and status colouring.
#
# CADENCE: daily incl. weekends at 5:00am CST (Megan 2026-07-19).
#
# WHY 5:00 AND NOT 5:30. Megan first asked for 5:30, but 5:30/5:38/5:46/5:54 is
# b2b_quality's retry ladder and that job MUST be finished by 6:00 (Sales
# Boards starts at 6:00; the VA posts by hand ~5:57). This pull is ~7 minutes
# on a ~120MB export plus a full Chrome-profile copy, so stacking it on 5:30
# risked pushing a live report past its last retry. 5:00 gives both jobs room.
# If this ever needs to move, keep it clear of 5:30-6:00.
#
# NO SLACK POST. This report only writes the sheet — unlike box_order_log there
# is no marker/one-post-per-day dance, because nothing is posted. Slack for the
# B2B thread is a separate, still-ungated piece of work.
#
# Manual test (pulls, writes NOTHING):  bash deploy/att_order_log.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.att_order_log.run" > /dev/null 2>&1; then
    echo "[$(date)] att-order-log SKIPPED — previous pass still running"
    exit 0
fi

# The mini runs 3.9; the laptop 3.14. Prefer the pinned interpreter when it is
# there, else whatever the venv provides — never hardcode one (cross-platform
# rule, and .venv/bin/python3.14 does not exist on Lucy 2).
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# --sheet writes the two tabs. Without it the module is a dry run by design,
# which is what --dry gives you for a manual check.
MODE="--sheet"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/att-order-log-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] att-order-log starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.att_order_log.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] att-order-log finished exit=$ST (mode: ${MODE:-dry-run})" >> "$LOG_FILE"
exit 0
