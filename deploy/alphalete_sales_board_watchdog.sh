#!/bin/bash
# Alphalete Sales Board WATCHDOG — every 20 minutes on LUCY 1 via launchd
# (com.alphalete.alphalete-sales-board-watchdog).
#
# Answers the one question the sweep's own alerting cannot: has it STOPPED?
# run.py alerts when a sweep runs and fails; a sweep that never fires writes
# nothing at all, and that silence is indistinguishable from a quiet evening.
#
#   bash deploy/alphalete_sales_board_watchdog.sh --dry-run   # preview, no DM
#
# The module itself exits outside selling hours and refuses to complain in the
# first 20 minutes of the day, so this runs on a plain interval and stays quiet.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/alphalete-sales-board-watchdog-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] watchdog starting" >> "$LOG_FILE"
"$VENV_PY" -m automations.alphalete_sales_board.watchdog "$@" >> "$LOG_FILE" 2>&1
echo "[$(date)] watchdog done (exit $?)" >> "$LOG_FILE"
