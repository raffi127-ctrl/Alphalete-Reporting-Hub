#!/bin/bash
# Interviewer Retention -- the side-by-side TEST WEEK (card step 4.2; Megan
# 2026-11-27: "run it for the next week and make sure it matches", "Lucy first").
# Once a day, Mon-Sat after 7:00 PM CT, Lucy fills the TEST COPY of Raf's ARS
# tab from AppStream, compares the week so far with what the interviewers typed
# on the real tab (read only), and DMs Megan, only Megan, the summary.
# Ticks every 30 min (com.alphalete.interviewer-retention-test.plist) on Lucy 3;
# the clock gate and the "already done today" check are in parallel.py (--due)
# and run before AppStream is opened, so an idle tick costs nothing.
#
# Manual:  bash deploy/interviewer_retention_test.sh --office 11280 --due --dm   (a tick)
#          bash deploy/interviewer_retention_test.sh --office 11280             (print only)
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick up pushed fixes before running (the pull is per wrapper, not per box).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# One pass at a time.
if pgrep -f "automations.interviewer_retention.parallel" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
export PYTHONPATH="$(pwd)"
mkdir -p output/logs
LOG="output/logs/interviewer_retention_test_$(date +%Y%m%d).log"

"$VENV_PY" -m automations.interviewer_retention.parallel "$@" >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "[$(date)] interviewer-retention-test rc=$rc" >> "$LOG"
fi
exit $rc
