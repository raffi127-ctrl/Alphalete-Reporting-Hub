#!/bin/bash
# Late Join Audit -- once a day, Mon-Sat after 6:30 PM CT, Lucy checks every
# 1st round "Late Join" in AppStream against the slot (5-min grace, Rafael
# 2026-09-30) and posts one thread in #ars-recruiting-numbers. Evenings, not
# mornings (Eve 2026-09-30: the morning is for the important reports). Ticks
# every 30 minutes (com.alphalete.late-join-audit.plist) on Lucy 2; the clock
# gate and the "day already posted" check are in run.py (--due) and run before
# AppStream is opened, so an idle tick costs nothing.
#
# Manual:  bash deploy/late_join_audit.sh --due --post                (a tick)
#          bash deploy/late_join_audit.sh --post --date 2026-09-29    (force a day)
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick up pushed fixes before running (the pull is per wrapper, not per box).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# One pass at a time: walking every office's calendar can outlast a tick.
if pgrep -f "automations.late_join_audit.run" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
export PYTHONPATH="$(pwd)"
mkdir -p output/logs
LOG="output/logs/late_join_audit_$(date +%Y%m%d).log"

"$VENV_PY" -m automations.late_join_audit.run "$@" >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "[$(date)] late-join-audit rc=$rc" >> "$LOG"
fi
exit $rc
