#!/bin/bash
# Campaign roster sync -> Vantura Master (every 30 min on LUCY 2).
# Moves reps between the main Sales Board and the D2D (Verizon) board when
# their Campaign column / Roll Call campaign says so. See the module docstring.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.vantura_slack_sales.roster_sync" > /dev/null 2>&1; then
    echo "[$(date)] vantura-roster-sync SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/vantura-roster-sync-$(date +%Y-%m-%d).log"
echo "[$(date)] pass" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.vantura_slack_sales.roster_sync >> "$LOG_FILE" 2>&1
exit $?
