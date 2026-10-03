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

echo "[$(date)] indeed-source-report START $*" >> "$LOG"
"$VENV_PY" -m automations.indeed_source_report.run "$@" >> "$LOG" 2>&1
rc=$?
echo "[$(date)] indeed-source-report END rc=$rc" >> "$LOG"

# ---- SCI PASS (captainship split, Carlos 2026-10-02) ------------------------
# Second run against the SCI Recruiting Dashboard with the 15 captainship-only
# owners as its org (deploy/sci-roster.json). Sequential on purpose — one
# AppStream session at a time. Exit is OR'd so a failed SCI pass is visible.
SCI_SSID="1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg"
echo "[$(date)] indeed-source-report SCI START $*" >> "$LOG"
INDEED_SOURCE_SPREADSHEET_ID="$SCI_SSID" \
    RECRUITING_ROSTER_JSON="$(pwd)/deploy/sci-roster.json" \
    "$VENV_PY" -m automations.indeed_source_report.run "$@" >> "$LOG" 2>&1
rc_sci=$?
echo "[$(date)] indeed-source-report SCI END rc=$rc_sci" >> "$LOG"
[ $rc -eq 0 ] && rc=$rc_sci
exit $rc
