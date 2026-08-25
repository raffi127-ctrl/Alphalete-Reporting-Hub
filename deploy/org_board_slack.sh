#!/bin/bash
# Org Sales Board — daily Slack post to #top-leaders-alphalete-org, AS LUCY.
# Runs on the mini (Lucy's token). launchd fires 11 passes 07:05-11:25 CST;
# the module's fill-gate holds (exit 75) until YESTERDAY's column is 100% filled,
# then posts once. A once-per-day state file makes the later passes no-ops.
#
# The 07:05 first slot sits deliberately BEHIND com.alphalete.org-board-box-repull
# (06:52 / 06:58), which tops off the BOX section the 04:50 fill was too early to
# get. See the plist comment; the wait-loop below is what enforces the ordering.
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

# WAIT for a board FILL to finish before exporting (Eve 2026-08-25). The Box
# top-off (com.alphalete.org-board-box-repull, 06:52 / 06:58) writes the BOX
# block a few minutes before this 07:05 slot; exporting mid-write would put a
# HALF-FILLED Box section in the picture the whole org reads, which is worse
# than the day-behind one this change exists to fix. Matches a full
# org_sales_board.run too — an orchestrator fill running long is the same
# hazard.
#
# WAIT, DO NOT SKIP. Skipping would push the post to the next ladder rung at
# 07:30 and drag the review link and the email past the 07:25 deadline, which
# is the entire point of the 07:05 slot. Bounded at 6 min so a hung pull can
# never hold the post indefinitely: past that we export anyway and take the
# stale-Box picture, because a post that goes out beats a post that does not.
_WAIT_LEFT=36
while pgrep -f "automations.org_sales_board.run" > /dev/null 2>&1; do
    if [ "$_WAIT_LEFT" -le 0 ]; then
        echo "[$(date)] a board fill is STILL running after 6 min — exporting anyway"
        break
    fi
    [ "$_WAIT_LEFT" = "36" ] && echo "[$(date)] a board fill is running — waiting for it before export"
    sleep 10
    _WAIT_LEFT=$((_WAIT_LEFT - 1))
done

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

# No-show marker: the agent FIRED (0 = posted, 75 = legitimately held/nothing to
# post). A missing marker past the deadline means launchd never ran it at all —
# the only silent-no-fire signal (a held day is NOT a miss). (2026-07-28)
case "$ST" in 0|75) touch "output/logs/.org-board-slack-ran-$(date +%Y-%m-%d)" 2>/dev/null || true ;; esac
exit 0
