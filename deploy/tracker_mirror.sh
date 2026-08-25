#!/bin/bash
# Tracker mirror — copy each manager's ad tracker (via the org tracker's
# still-authorized IMPORTRANGE staging tabs) into Alphalete Recruiting Dashboard.
# TIME KNOB: StartCalendarInterval in deploy/com.alphalete.tracker-mirror.plist.
# Manual: bash deploy/tracker_mirror.sh [--only "Name"] [--dry-run]
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.tracker_mirror.run" > /dev/null 2>&1; then
    echo "[$(date)] tracker-mirror SKIPPED — previous pass still running"; exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/tracker_mirror_$(date +%Y%m%d).log"

# STOOD DOWN? run.py refuses too, but bail HERE so the stand-down never touches
# the Hub: publishing a 'success' for a pass that ferried nothing would paint the
# card green and tell everyone not to look (2026-08-24).
if [ -f automations/tracker_mirror/DISABLED ]; then
    echo "[$(date)] tracker-mirror STOOD DOWN (automations/tracker_mirror/DISABLED) — not running, not publishing" >> "$LOG"
    exit 0
fi

# A rehearsal must never mark the card green (same gate as brand_audit_noon.sh).
PUBLISH=1
case " $* " in *" --dry-run "*) PUBLISH=0 ;; esac

# Open a live 'running' pill so the card pulses while the ferry works. The gate
# MUST match the publish_done below or a dry run strands a yellow pill.
RUN_ID=""
if [ "$PUBLISH" -eq 1 ]; then
    RUN_ID=$("$VENV_PY" -c "from automations.day_orchestrator import hub_publish; print(hub_publish.publish_running('tracker_mirror','Tracker Mirror') or '')" 2>>"$LOG")
fi

echo "[$(date)] tracker-mirror START $*" >> "$LOG"
"$VENV_PY" -m automations.tracker_mirror.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] tracker-mirror END rc=$rc" >> "$LOG"

# Report this launchd run to the Hub — without this the card NEVER goes green no
# matter how many clean 7:30 passes land (the only row it ever had came from a
# `lucy rerun`). rc=2 is run.py's "ferried, but kept previous values for some
# managers" — that's 'partial', not a silent green and not a Slack page.
if [ "$PUBLISH" -eq 1 ]; then
    case "$rc" in
        0) ST=success ;;
        2) ST=partial ;;
        *) ST=failed ;;
    esac
    "$VENV_PY" -c "
import sys
from automations.day_orchestrator import hub_publish
rid = sys.argv[1] or None
hub_publish.publish_done('tracker_mirror', 'Tracker Mirror', sys.argv[2], rid)
" "$RUN_ID" "$ST" >> "$LOG" 2>&1 || true
fi
exit $rc
