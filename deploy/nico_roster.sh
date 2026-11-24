#!/bin/bash
# Nico's payroll book: rebuild 'Active Reps' and the three check panels on the
# newest WE tab (Carlos 2026-11-24). Fired by launchd on LUCY 2:
# com.alphalete.nico-roster at 7:10am, 1:10pm, 6:10pm and 9:15pm.
#
# See automations/nico_roster_check/run.py + panels.py.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nico-roster-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] nico roster + panels starting" >> "$LOG_FILE"
"$VENV_PY" -m automations.nico_roster_check.run --write --panels "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] nico roster + panels done (exit $rc)" >> "$LOG_FILE"
exit $rc
