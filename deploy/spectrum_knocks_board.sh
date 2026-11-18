#!/bin/bash
# Spectrum Knocks board — a picture of every Spectrum rep's day in
# #alphalete-sales-knocking-data at 2:00 PM, 5:15 PM and 9:00 PM CT, Mon-Sat
# (Raf + Eve 2026-11-18, same moments as the OwnerVille intraday boards).
# --text: the same picture also goes to the iMessage room "Knocking Chat A-Players".
# The agent ticks every 5 min; board.py posts each slot once, when it's due.
# Manual preview (draws the PNG, posts nothing): bash deploy/spectrum_knocks_board.sh --slot eod --force
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.spectrum_knocks.board" > /dev/null 2>&1; then
    exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
export PYTHONIOENCODING=utf-8
mkdir -p output/logs
LOG="output/logs/spectrum_knocks_board_$(date +%Y%m%d).log"
echo "--- $(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
"$VENV_PY" -m automations.spectrum_knocks.board "$@" >> "$LOG" 2>&1
exit $?
