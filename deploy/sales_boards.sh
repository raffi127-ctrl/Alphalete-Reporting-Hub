#!/bin/bash
# Program Sales Boards -> #alphalete-gp-sales, AS LUCY, on the mini.
# Posts one dated thread ("Vantura Production MM/DD/YYYY") with each program's
# two images (weekly ranking + Highrollers) as threaded replies.
#
# CADENCE: daily incl. weekends, 6:00am CST + q25m retries as a safety net. The
# module HOLDS (exit 75) when the board's gold WE cell isn't the week containing
# yesterday (matters Mondays), and skips boards already in today's thread — so
# the later passes are no-ops once it has posted.
#
# Manual test (dry-run, no post):  bash deploy/sales_boards.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.sales_boards.run" > /dev/null 2>&1; then
    echo "[$(date)] sales-boards SKIPPED — previous pass still running"
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

MODE="--post"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/sales-boards-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] sales-boards starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.sales_boards.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 75 = wrong-week hold; expected, the next pass retries.
echo "[$(date)] sales-boards finished exit=$ST" >> "$LOG_FILE"
exit 0
