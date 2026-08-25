#!/bin/bash
# Intraday knock boards, on each office's OWN clock. Runs every 5 minutes and
# posts whatever is due; most passes do nothing and exit 0 in a second.
#   2:00 PM  first knocks  — Cody only (Megan 2026-08-25)
#   5:15 PM  money lap     — Cody only
#   9:00 PM  end of day    — every enrolled office, its own local 9 PM
#            (Raf 2026-08-25 asked for every office; Megan made it local)
# THE TIMES ARE IN schedule.py, NOT in the plist — the plist only sets how
# often we check. That is what lets one job serve two timezones.
# Manual: bash deploy/knocks_intraday.sh --tick --send   (no --send = dry-run)
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.knocks_intraday.run" > /dev/null 2>&1; then
    echo "[$(date)] knocks-intraday SKIPPED — previous pass still running"; exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/knocks_intraday_$(date +%Y%m%d).log"

# A rehearsal must never mark the card green (same gate as tracker_mirror.sh).
# No --send = dry-run, so it neither posts nor publishes.
#
# AND a tick that had nothing due must not publish either: this job wakes ~170
# times a day and only ~4 of those do anything. Publishing every quiet tick
# would repaint the card all day and bury the runs that mattered. So the shell
# runs first and only publishes if the run reported work — see WORKED below.
PUBLISH=0
case " $* " in *" --send "*) PUBLISH=1 ;; esac

echo "[$(date)] knocks-intraday START $*" >> "$LOG"
"$VENV_PY" -m automations.knocks_intraday.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] knocks-intraday END rc=$rc" >> "$LOG"

# Did this pass actually do anything? The run prints a "<slot>: posted=" line
# only when a slot fired. A quiet tick leaves the card exactly as it was.
WORKED=0
grep -q "posted=" "$LOG" 2>/dev/null && \
  tail -40 "$LOG" | grep -q "posted=" && WORKED=1

if [ "$PUBLISH" -eq 1 ] && [ "$WORKED" -eq 1 ]; then
    "$VENV_PY" -c "
from automations.day_orchestrator import hub_publish
rid = hub_publish.publish_running('knocks_intraday', 'Intraday Knocks')
hub_publish.publish_done('knocks_intraday', 'Intraday Knocks', status=('success' if $rc == 0 else 'failed'), run_id=rid or None)
" >> "$LOG" 2>&1
fi
exit $rc
