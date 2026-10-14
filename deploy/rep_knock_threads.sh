#!/bin/bash
# Rep Knock Threads — hourly per-rep knocking cards in #alphalete-sales-knocking-data.
# The agent ticks every 10 min; run.py posts once per clock hour, 10 AM–9 PM CT
# (hours in automations/rep_knock_threads/config.py, not here).
# Manual: bash deploy/rep_knock_threads.sh --send --force   (no --send = dry-run)
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.rep_knock_threads.run" > /dev/null 2>&1; then
    exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/rep_knock_threads_$(date +%Y%m%d).log"
START=0; [ -f "$LOG" ] && START=$(wc -l < "$LOG"); START=$((START + 0))

"$VENV_PY" -m automations.rep_knock_threads.run "$@" >> "$LOG" 2>&1
rc=$?

# Publish to the Hub only when this pass actually posted or failed — a quiet
# tick (outside hours / hour already done) must not repaint the card.
# Never on a dry-run.
case " $* " in *" --send "*)
    LINE=$(tail -n +"$((START + 1))" "$LOG" | grep -oE '\[rep_knocks\] posted=[0-9]+ skipped=[0-9]+ failed=[0-9]+' | tail -1)
    if [ -n "$LINE" ] || [ $rc -ne 0 ]; then
        if [ $rc -eq 0 ]; then _PUB=success; else _PUB=failed; fi
        "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('rep_knock_threads','Rep Knock Threads','$_PUB')" >> "$LOG" 2>&1 || true
    fi
    ;;
esac
exit $rc
