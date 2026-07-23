#!/bin/bash
# Vantura Sales Board fill from #alphalete-gp-sales, on LUCY 2 (Carlos's mac).
# Counts Base / BOX / AT&T sales out of the channel's posts and writes the day
# column on the "Sales Board" tab.
#
# CADENCE (Megan 2026-07-23): 4,5,6,7,8,9pm fill the day IN PROGRESS so the
# board is live through the evening; 5:00am closes out the PREVIOUS day, which
# is what makes the 5:10am sales_boards post possible (that post sat at 7:00am
# only because the day cells were still being hand-entered).
#
# The target day comes from the clock — before 10am the run is finishing
# yesterday, after it the run is filling today — so this wrapper passes no
# --date and the same plist covers both the evening and morning passes.
#
# BACKFILL IS AUTOMATIC: every pass recomputes the whole day from scratch and
# only writes cells whose value changed, so a rep who posts late (or posts the
# next morning tagged YESTERDAY) is picked up by the next pass. Reps who posted
# nothing are never written, so a hand-entered number is never zeroed out.
#
# Manual test (no writes):  bash deploy/vantura_slack_sales.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.vantura_slack_sales.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-slack-sales SKIPPED — previous pass still running"
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

MODE="--fill --yes"
[ "${1:-}" = "--dry" ] && MODE="--fill"

LOG_FILE="$LOG_DIR/vantura-slack-sales-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] vantura-slack-sales starting (mode: $MODE)" > "$LOG_FILE"

"$VENV_PY" -u -m automations.vantura_slack_sales.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] vantura-slack-sales finished exit=$ST" >> "$LOG_FILE"
exit 0
