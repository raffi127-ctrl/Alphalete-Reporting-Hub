#!/bin/bash
# The morning + week-table texts as ONE PDF each (Carlos 2026-11-27).
# Fired by launchd on LUCY 2: com.alphalete.text-bundles at each bundle tick
# (morning 7:30/7:45/8:00/8:30 daily; weeks 11:35/11:45/12:00 Mon-Fri).
# Each tick sends a bundle only once all its parts are in, or at its last
# tick with whatever is there. See automations/text_bundles/config.py.
#
#   bash deploy/text_bundles.sh                   # what launchd runs (--due)
#   python -m automations.text_bundles.run --bundle morning --dm U...   # preview

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/text-bundles-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] text bundles tick" >> "$LOG_FILE"
"$VENV_PY" -m automations.text_bundles.run --due "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] text bundles done (exit $rc)" >> "$LOG_FILE"
exit $rc
