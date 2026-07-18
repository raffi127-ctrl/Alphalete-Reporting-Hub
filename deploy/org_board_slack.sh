#!/bin/bash
# Org Sales Board — daily Slack post to #top-leaders-alphalete-org, AS LUCY.
# Runs on the mini (Lucy's token). launchd fires 8 passes 9:00-11:55 CST q25m;
# the module's fill-gate holds (exit 75) until YESTERDAY's column is 100% filled,
# then posts once. A once-per-day state file makes the later passes no-ops.
#
# CADENCE: daily incl. weekends (no Weekday key in the plist). TIME KNOB: edit
# StartCalendarInterval in deploy/com.alphalete.org-board-slack.plist, not here.
#
# Manual test (dry-run, no post):  bash deploy/org_board_slack.sh --dry
#   (pass --dry to force the module's dry-run; default here is LIVE --post.)
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: a slow export shouldn't be fought by the next 25-min tick.
if pgrep -f "automations.org_sales_board.slack_post" > /dev/null 2>&1; then
    echo "[$(date)] org-board slack SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# LIVE by default (--post). Pass "--dry" to this wrapper to force a dry-run.
MODE="--post"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/org-board-slack-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] org-board slack starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.org_sales_board.slack_post $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 75 = fill-gate held (yesterday not fully entered yet) — expected; the next
# scheduled pass retries. Any other non-zero is a real error worth the log.
echo "[$(date)] org-board slack finished exit=$ST" >> "$LOG_FILE"
exit 0
