#!/bin/bash
# New DU status reconcile -> Vantura Master (Sundays 7pm CT on LUCY 2).
# Flips Active/Orientation-Scheduled DU rows to Not Active when the person's
# newest Roll Call row is Terminated / T-marked. See the module docstring.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.vantura_du_status.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-du-status SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/vantura-du-status-$(date +%Y-%m-%d-%H%M%S).log"
"$VENV_PY" -u -m automations.vantura_du_status.run --write >> "$LOG_FILE" 2>&1
ST=$?
if [ $ST -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(":rotating_light: *New DU status reconcile* failed",
                      ["```"] + tail + ["```",
                       'Re-run: `lucy rerun vantura_du_status --machine "Lucy 2"`'],
                      tag="vantura_du_status-failed", cfg=load_config(),
                      incident="vantura-du-status-failed")
except Exception as e:
    print("alert failed:", e)
PY
fi
exit $ST
