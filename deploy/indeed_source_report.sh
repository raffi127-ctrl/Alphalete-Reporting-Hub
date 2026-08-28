#!/bin/bash
# Indeed Ad Performance dashboard — refresh the CURRENT month from AppStream's
# Source Report (p=702) for every tracked manager, three times a day.
#
# Writes ONLY the current month plus each manager's recomputed YTD block; earlier
# months on the DATA tab are left alone.
#
# TIME KNOB: edit StartCalendarInterval in
#   deploy/com.alphalete.indeed-source-report.plist
# then re-install:
#   python -m automations.day_orchestrator.install_agent indeed-source-report
#
# Manual dry test (pulls everything, writes nothing):
#   bash deploy/indeed_source_report.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: 28 offices x ~8s can run long, and 12:00 must not fight a slow
# 04:00 pass still holding the AppStream session.
if pgrep -f "automations.indeed_source_report.run" > /dev/null 2>&1; then
    echo "[$(date)] indeed-source-report SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/indeed_source_report_$(date +%Y%m%d).log"

# STOOD DOWN? run.py refuses too, but bail HERE so the stand-down never touches
# the Hub: publishing a run for a pass that pulled nothing would paint the card
# and tell everyone not to look (same gate as tracker_mirror.sh, 2026-08-24).
if [ -f automations/indeed_source_report/DISABLED ]; then
    echo "[$(date)] indeed-source-report STOOD DOWN (automations/indeed_source_report/DISABLED) — not running, not publishing" >> "$LOG"
    exit 0
fi

echo "[$(date)] indeed-source-report START $*" >> "$LOG"
"$VENV_PY" -m automations.indeed_source_report.run "$@" >> "$LOG" 2>&1
rc=$?
echo "[$(date)] indeed-source-report END rc=$rc" >> "$LOG"
exit $rc
