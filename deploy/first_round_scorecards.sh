#!/bin/bash
# 1st Round Scorecards -- once a day, Mon-Fri after 6 PM CT, Lucy grades every
# 1st round Fathom recorded today and posts one thread per interviewer in
# #ars-recruiting-numbers (Rafael / Eve, 2026-09-29). Ticks every 30 minutes
# (com.alphalete.first-round-scorecards.plist); the clock gate and the "day
# already posted" check are in run.py (--due) and run before any Fathom or AI
# call, so an idle tick costs nothing.
#
# Manual:  bash deploy/first_round_scorecards.sh --due --post        (a tick)
#          bash deploy/first_round_scorecards.sh --post --date 2026-09-28   (force a day)
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick up pushed fixes before running (the pull is per wrapper, not per box).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# One pass at a time: grading a day of interviews can outlast a tick.
if pgrep -f "automations.first_round_scorecards.run" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
export PYTHONPATH="$(pwd)"
mkdir -p output/logs
LOG="output/logs/first_round_scorecards_$(date +%Y%m%d).log"

"$VENV_PY" -m automations.first_round_scorecards.run "$@" >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "[$(date)] first-round-scorecards rc=$rc" >> "$LOG"
fi
exit $rc
