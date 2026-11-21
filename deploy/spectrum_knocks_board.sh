#!/bin/bash
# Spectrum Knocks board — a picture of every Spectrum rep's day, Mon-Sat:
# #alphalete-sales-knocking-data every hour 10 AM-9 PM CT, and #alphalete-sales
# every 30 min inside Raf's board hours (Raf 2026-11-21). The times live in
# board.py, not here.
# --text: the same picture also goes to the iMessage room "Knocking Chat A-Players" (2 / 5 / 9 PM).
# The agent ticks every 5 min; board.py posts each slot once, when it's due.
# Manual preview (draws the PNG, posts nothing): bash deploy/spectrum_knocks_board.sh --tick
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
