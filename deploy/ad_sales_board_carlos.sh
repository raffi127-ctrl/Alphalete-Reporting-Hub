#!/bin/bash
# Ad Sales Board — CARLOS FAST LANE: office 11580 only, every 30 minutes
# 07:05-21:35 (Carlos 2026-10-20: "lets have the 17 org offices update only
# once a day and mine update every 30 mins"). The full-org pass is
# com.alphalete.ad-sales-board, once daily at 07:50; this agent keeps ONE
# office fresh in between without re-pulling the other 27.
#
#   --office 11580   pull only Carlos Hidalgo's office. run.py's freeze rule
#                    ("rewrite only the (manager, week) pairs this run pulled")
#                    carries every other office's stored rows through untouched.
#   --today          also pull TODAY's partial day report, so the in-progress
#                    day's AC..AI cell shows live numbers instead of staying
#                    blank; each pass replaces it, and the next day's normal
#                    yesterday-pull writes the final count.
#   --no-activity    skip the hub activity row — ~30 runs/day would drown the
#                    activity log. Failure alerts still post, incident-threaded.
#
# NO SCI pass here: captainship refreshes once a day with the main agent.
#
# TIME KNOB: edit StartCalendarInterval in
#   deploy/com.alphalete.ad-sales-board-carlos.plist
# then re-install:
#   lucy rerun install_ad_sales_board_carlos_agent  (machine: Lucy 2)
#
# Manual dry test (pulls, writes nothing):
#   bash deploy/ad_sales_board_carlos.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard — same pattern (and same pattern string) as ad_sales_board.sh,
# so this also catches the daily full-org pass and its SCI pass: while either
# is running this tick just exits, and the next one is 30 minutes away. Two
# ad_sales_board runs at once would fight for the AppStream session AND
# last-writer-wins each other's full-range sheet write.
if pgrep -f "automations.ad_sales_board.run" > /dev/null 2>&1; then
    echo "[$(date)] ad-sales-board-carlos SKIPPED — another ad_sales_board pass is running"
    exit 0
fi

# ---- SELF-UPDATE FROM GITHUB ------------------------------------------------
# Same rule as ad_sales_board.sh: GitHub is the deploy channel that always
# works; best-effort, --ff-only, and never longer than 60s (perl alarm —
# macOS ships no `timeout`).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi
# -----------------------------------------------------------------------------

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/ad_sales_board_carlos_$(date +%Y%m%d).log"

echo "[$(date)] ad-sales-board-carlos START $*" >> "$LOG"
"$VENV_PY" -m automations.ad_sales_board.run \
    --office 11580 --today --no-activity "$@" >> "$LOG" 2>&1
rc=$?
echo "[$(date)] ad-sales-board-carlos END rc=$rc" >> "$LOG"
exit $rc
