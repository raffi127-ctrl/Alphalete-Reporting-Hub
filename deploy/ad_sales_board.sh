#!/bin/bash
# Ad Sales Board — the Source Report week by week (pull + names), refreshed
# EVERY TWO HOURS 07:50-21:50 (Carlos 2026-08-27). The 07:50 anchor is kept
# because it lands after applicant_tracker's 6:45 morning import puts yesterday's
# names in; the later passes pick up the day as it fills.
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

# ---- SELF-UPDATE FROM GITHUB ------------------------------------------------
# Same rule as applicant_push.sh and day_orchestrator.sh: GitHub is the deploy
# channel that always works. The Mini Control queue is a single-threaded poller
# and can sit blocked for hours behind one long report, so a job that now runs
# every two hours must not depend on it to pick up a fix. Best-effort and
# --ff-only: a failed pull leaves yesterday's code running rather than skipping
# the refresh.
if [ -d .git ]; then
  git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi
# -----------------------------------------------------------------------------

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
