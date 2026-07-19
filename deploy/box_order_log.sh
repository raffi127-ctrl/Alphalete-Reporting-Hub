#!/bin/bash
# BOX Order Log -> "Lucy Box Order Log" tab on the Vantura Master Sales Board.
#
# Pulls Carlos's BoxOrderLog Tableau view, collapses the status-transition rows
# into one row per sale, and MERGES the result into the sheet's rolling
# six-week log — new sales appended, status changes updated in place, the
# oldest week dropped once it falls out of the window.
#
# CADENCE: daily incl. weekends, 7:00am CST, with retries through the morning.
# The merge is idempotent (a second pass on unchanged data is a no-op that
# reports "0 new, 0 status changes"), so the retries are free insurance
# against a Tableau render flake or a cold ownerville session.
#
# Does NOT post to Slack. Carlos reads this in the sheet; the PDF path exists
# (--pdf/--post) but is deliberately not wired here.
#
# Manual test (no writes to the sheet):  bash deploy/box_order_log.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.box_order_log.run" > /dev/null 2>&1; then
    echo "[$(date)] box-order-log SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Two deliverables per run, and they are deliberately different scopes:
#   --sheet  merges the rolling SIX-WEEK log into the Vantura board
#   --xlsx   writes the day's FULL pull to output/, one tab per rep
MODE="--sheet --xlsx"
[ "${1:-}" = "--dry" ] && MODE="--xlsx"

LOG_FILE="$LOG_DIR/box-order-log-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] box-order-log starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.box_order_log.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] box-order-log finished exit=$ST" >> "$LOG_FILE"
exit 0
