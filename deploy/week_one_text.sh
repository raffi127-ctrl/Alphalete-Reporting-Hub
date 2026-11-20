#!/bin/bash
# Week-table pictures (AT&T/NDS + Verizon Sales Boards) -> the NEW A Players
# chain (Carlos 2026-11-19). Fired by launchd on LUCY 2, Monday-Friday:
#   com.alphalete.week-one-text     10:45 (+10:55 retry)  --send               WEEK 1, cut at today
#   com.alphalete.week-tables-text  11:30 (+11:40 retry)  --shot weeks --send  WEEK 1-4
# Each board texts once per day per shot.
#
#   bash deploy/week_one_text.sh                       # DRY RUN, renders only
#   bash deploy/week_one_text.sh --shot weeks --send   # queue the 11:30 texts
#
# See automations/week_one_text/run.py.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/week-one-text-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] week one text starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.week_one_text.run "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] week one text done (exit $rc)" >> "$LOG_FILE"
exit $rc
