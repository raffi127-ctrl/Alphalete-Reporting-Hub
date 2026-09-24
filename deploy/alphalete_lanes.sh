#!/bin/bash
# Alphalete Sales Board — keep the 'Lanes' tab on the right two weeks.
# Every 10 minutes on LUCY 1 via launchd (com.alphalete.alphalete-lanes).
#
#   bash deploy/alphalete_lanes.sh             # PREVIEW, writes nothing
#   bash deploy/alphalete_lanes.sh --apply     # write
#
# Monday: flips the lanes on the first tick after Eve builds the new
# 'Sales Board WE <m>.<d>' tab (~6:00-7:30 CT). Other days: re-points the end
# row if a rep row was added above TOTALS. Writes nothing when nothing moved.
# See automations/alphalete_sales_board/lanes.py.

set -u
cd "$(dirname "$0")/.." || exit 1

HOUR=$(date +%H)
HOUR=${HOUR#0}
# 06:00-21:59 every day. Off-hours ticks cost a few ms here.
{ [ "$HOUR" -lt 6 ] || [ "$HOUR" -gt 21 ]; } && exit 0

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/alphalete-lanes-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] lanes starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.alphalete_sales_board.lanes "$@" >> "$LOG_FILE" 2>&1
rc=$?   # grab before $(date) resets it
echo "[$(date)] lanes done (exit $rc)" >> "$LOG_FILE"
exit $rc
