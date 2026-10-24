#!/bin/bash
# NDS Sales Board fill from Carlos's NDS SaraPlus, via the ICD relay, on LUCY 2.
# Reads the latest relay snapshot of the day for Carlos's NDS office (the
# 'ICD Relay' tab his office mini writes every few minutes) and SETS each
# matched rep's day cell on the "NDS Sales Board" tab to Int + NL -- Megan's
# SaraPlus-is-the-truth rule (up or down), board reps absent from SaraPlus
# left as-is, unmatched names flagged. Upgrades, tablets and wearables never
# count (Carlos 2026-10-23); DTV is logged, not counted.
#
# CADENCE: the same clock as vantura_slack_sales (16:00-21:00 hourly fills the
# day IN PROGRESS; 05:00 closes out YESTERDAY from the mini's 2am catch-up
# relay, before com.alphalete.sales-boards' 05:10 post). The target day comes
# from the clock (before 10am = yesterday), so this wrapper passes no --date.
#
# HOLDS (exit 75, nothing written, Hub pill amber): no relay row for the day
# (the office mini is off / asleep), the board's gold WE cell on another week,
# no column for the day. The next pass retries.
#
# Manual test (no writes):   bash deploy/vantura_nds_sara.sh --dry
# What relayed, no writes:   bash deploy/vantura_nds_sara.sh --probe
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.vantura_nds_sara.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-nds-sara SKIPPED — previous pass still running"
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
[ "${1:-}" = "--probe" ] && MODE="--probe"
LIVE=1
[ "${1:-}" = "--dry" ] && LIVE=0
[ "${1:-}" = "--probe" ] && LIVE=0

LOG_FILE="$LOG_DIR/vantura-nds-sara-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] vantura-nds-sara starting (mode: $MODE)" > "$LOG_FILE"

# Live 'running' pill so the Hub card pulses while the pass works; publish_done
# below closes the same row (same contract as vantura_slack_sales.sh). Skipped
# on --dry / --probe: a preview must not blink the card as a real run.
if [ "$LIVE" = "1" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('vantura_nds_sara','NDS Sales Board Fill (SaraPlus relay)')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.vantura_nds_sara.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] vantura-nds-sara finished exit=$ST" >> "$LOG_FILE"

# Done-marker + Hub pill, same contract as vantura_slack_sales.sh: marker =
# "a pass ran today"; the Hub card is how a silent launchd miss gets seen.
# exit 75 = HOLD (no relay / wrong week / no column): nothing written and that
# is correct, so not a failure -- but not a success either: amber.
if [ "$LIVE" = "1" ]; then
    touch "$LOG_DIR/.vantura-nds-sara-done-$(date +%Y-%m-%d)"
    find "$LOG_DIR" -name ".vantura-nds-sara-done-*" -mtime +3 -delete 2>/dev/null
    case "$ST" in
        0)  _PUB=success ;;
        75) _PUB=partial ;;
        *)  _PUB=failed  ;;
    esac
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_nds_sara','NDS Sales Board Fill (SaraPlus relay)','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit 0
