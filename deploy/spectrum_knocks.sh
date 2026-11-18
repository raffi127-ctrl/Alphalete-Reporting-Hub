#!/bin/bash
# Spectrum Knocks — per-rep doors from Charter OpenDoor into the "Spectrum Knocks"
# tab of VAs' Data, every 15 min like the OwnerVille knocks (Eve 2026-11-18).
# The agent ticks every 15 min; fill.py decides the day (today 9 AM-midnight CT,
# yesterday in the midnight hour, nothing otherwise). No browser.
# Manual: bash deploy/spectrum_knocks.sh --tick
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.spectrum_knocks.fill" > /dev/null 2>&1; then
    exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/spectrum_knocks_$(date +%Y%m%d).log"
echo "--- $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
"$VENV_PY" -m automations.spectrum_knocks.fill "$@" >> "$LOG" 2>&1
exit $?
