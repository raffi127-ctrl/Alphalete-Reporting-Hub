#!/bin/bash
# Vantura Reps contacts sync -> alphaletegp@gmail.com Google Contacts
# (daily 9:30pm CT on LUCY 2, after the 8:45pm Daily Update fill).
# Creates a contact for every Active / Orientation-Scheduled rep on the Vantura
# master's Daily Update, name "<Name> (<CAMPAIGN>)", and appends/fixes the
# campaign parenthetical on ones already in the group. See the module docstring.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.vantura_contacts_sync.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-contacts-sync SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/vantura-contacts-sync-$(date +%Y-%m-%d-%H%M%S).log"
"$VENV_PY" -u -m automations.vantura_contacts_sync.run --write >> "$LOG_FILE" 2>&1
ST=$?
if [ $ST -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(":rotating_light: *Vantura Reps contacts sync* failed",
                      ["```"] + tail + ["```",
                       'Re-run: `lucy rerun vantura_contacts_sync --machine "Lucy 2"`'],
                      tag="vantura_contacts_sync-failed", cfg=load_config(),
                      incident="vantura-contacts-sync-failed")
except Exception as e:
    print("alert failed:", e)
PY
fi
exit $ST
