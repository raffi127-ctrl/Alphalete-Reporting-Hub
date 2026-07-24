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

# Report this standalone run to the Hub (shared Hub Activity sheet) so the card's
# pill reflects a REAL success/failure — the orchestrator publishes the reports IT
# runs, and a launchd job bypasses it entirely, so without this a clean run is
# indistinguishable from a silent miss. Skipped on --dry (a preview must not mark
# the card as ran). Best-effort — never fails the job.
# exit 75 = wrong-week HOLD (the board's gold WE cell is on another week).
# Nothing was written and that is correct behaviour, so it isn't a failure —
# but it isn't a success either, so the card goes amber rather than green.
if [ "${1:-}" != "--dry" ]; then
    case "$ST" in
        0)  _PUB=success ;;
        75) _PUB=partial ;;
        *)  _PUB=failed  ;;
    esac
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_slack_sales','Sales Board Fill','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

# A failure here is silent otherwise — nobody watches this log, and the 5:10am
# board post will happily render an unfilled day.
#
# A wrong-week HOLD only alerts on the MORNING pass. An evening hold means the
# board hasn't been rolled to the new week yet, which is normal on a Monday
# afternoon and would otherwise fire six times; the morning one is the one that
# matters, because the 5:10am post goes out ten minutes later.
_ALERT=no
[ "$ST" -ne 0 ] && [ "$ST" -ne 75 ] && _ALERT=yes
[ "$ST" -eq 75 ] && [ "$(date +%H)" -lt 10 ] && _ALERT=yes
if [ "$_ALERT" = "yes" ]; then
    "$VENV_PY" -m automations.vantura_slack_sales.alert "$LOG_FILE" "$ST" >> "$LOG_FILE" 2>&1 || true
fi
exit 0
