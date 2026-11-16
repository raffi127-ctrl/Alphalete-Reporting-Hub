#!/bin/bash
# Recruiting Day Texts clock (Megan 2026-11-13; own timer since 2026-11-16).
#
# RUNS ON LUCY 1. Fires at 6/7/8/9 AM and 2:45/3:45/4:45/5:45 PM Central,
# Mon-Sat (com.alphalete.recruiting-day-texts). Each firing asks the dispatcher
# which offices are at THEIR OWN 7:00 AM (good-morning text) or 3:45 PM
# (new-start retention text) and queues the AppStream read with NO machine, so
# routing hands it to the lighter of Lucy 1 / Lucy 3. The send always leaves
# from Lucy 1.
#
# Why a timer and not the Report Library card: no machine runs the card
# scheduler, so the 11/16 morning never fired.
#
#   bash deploy/recruiting_day_texts_clock.sh      # same as the timer
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/recruiting-day-texts-clock-$(date +%Y-%m-%d).log"
echo "[$(date)] recruiting-day-texts clock" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.recruiting_day_texts.dispatch >> "$LOG_FILE" 2>&1
RC=$?
echo "[$(date)] exit $RC" >> "$LOG_FILE"
exit $RC
