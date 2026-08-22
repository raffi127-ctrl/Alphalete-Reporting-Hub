#!/bin/bash
# Tracker mirror — copy each manager's ad tracker (via the org tracker's
# still-authorized IMPORTRANGE staging tabs) into Alphalete Manager Boards.
# TIME KNOB: StartCalendarInterval in deploy/com.alphalete.tracker-mirror.plist.
# Manual: bash deploy/tracker_mirror.sh [--only "Name"] [--dry-run]
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.tracker_mirror.run" > /dev/null 2>&1; then
    echo "[$(date)] tracker-mirror SKIPPED — previous pass still running"; exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/tracker_mirror_$(date +%Y%m%d).log"
echo "[$(date)] tracker-mirror START $*" >> "$LOG"
"$VENV_PY" -m automations.tracker_mirror.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] tracker-mirror END rc=$rc" >> "$LOG"; exit $rc
