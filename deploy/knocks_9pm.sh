#!/bin/bash
# 9 PM Central knock board — every enrolled office, the CURRENT day.
# Raf 2026-08-25: "Can we have this Daily knocks Post for every office at
# 9:00PM CEN please? I want people to look at it at night for break downs."
# TIME KNOB: StartCalendarInterval in deploy/com.alphalete.knocks-9pm.plist.
# Manual: bash deploy/knocks_9pm.sh --send   (no --send = dry-run, no post)
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.knocks_intraday.run" > /dev/null 2>&1; then
    echo "[$(date)] knocks-9pm SKIPPED — previous pass still running"; exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/knocks_9pm_$(date +%Y%m%d).log"

# A rehearsal must never mark the card green (same gate as tracker_mirror.sh).
# No --send = dry-run, so it neither posts nor publishes.
PUBLISH=0
case " $* " in *" --send "*) PUBLISH=1 ;; esac

RUN_ID=""
if [ "$PUBLISH" -eq 1 ]; then
    RUN_ID=$("$VENV_PY" -c "from automations.day_orchestrator import hub_publish; print(hub_publish.publish_running('knocks_9pm','Knocks 9 PM') or '')" 2>>"$LOG")
fi

echo "[$(date)] knocks-9pm START $*" >> "$LOG"
"$VENV_PY" -m automations.knocks_intraday.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] knocks-9pm END rc=$rc" >> "$LOG"

if [ "$PUBLISH" -eq 1 ]; then
    "$VENV_PY" -c "
from automations.day_orchestrator import hub_publish
hub_publish.publish_done('knocks_9pm', 'Knocks 9 PM', ok=($rc == 0), run_id='$RUN_ID' or None)
" >> "$LOG" 2>&1
fi
exit $rc
