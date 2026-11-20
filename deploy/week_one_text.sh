#!/bin/bash
# NDS Week 1 table picture -> the NEW A Players chain (Carlos 2026-11-19).
# Fired by launchd (com.alphalete.week-one-text) on LUCY 2 at 10:45 AM
# Monday-Friday, with a 10:55 retry; texts once per day.
#
#   bash deploy/week_one_text.sh            # DRY RUN, renders the picture only
#   bash deploy/week_one_text.sh --send     # queue the text
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
