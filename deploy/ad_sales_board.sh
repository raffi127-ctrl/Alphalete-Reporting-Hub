#!/bin/bash
# Ad Sales Board — the Source Report week by week (pull + names), refreshed
# daily after applicant_tracker's 6:45 morning import lands yesterday's names.
#
# Rewrites ONLY the current + previous ad-week (Wed→Tue) per office; older
# weeks on 'Ad Sales Data' stay frozen. On Wednesdays it also flips the visible
# tab's week picker to the week that just finished.
#
# TIME KNOB: edit StartCalendarInterval in
#   deploy/com.alphalete.ad-sales-board.plist
# then re-install:
#   python -m automations.day_orchestrator.install_agent ad-sales-board
#
# Manual dry test (pulls everything, writes nothing):
#   bash deploy/ad_sales_board.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: 28 offices x 2 weeks can run ~25 min; a manual rerun must not
# fight the scheduled pass for the AppStream session.
if pgrep -f "automations.ad_sales_board.run" > /dev/null 2>&1; then
    echo "[$(date)] ad-sales-board SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/ad_sales_board_$(date +%Y%m%d).log"

echo "[$(date)] ad-sales-board START $*" >> "$LOG"
"$VENV_PY" -m automations.ad_sales_board.run "$@" >> "$LOG" 2>&1
rc=$?
echo "[$(date)] ad-sales-board END rc=$rc" >> "$LOG"
exit $rc
