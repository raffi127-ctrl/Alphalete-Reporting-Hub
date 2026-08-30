#!/bin/bash
# Vantura B2B Revenue Board -> the Vantura Production thread, on LUCY 2.
# Prices the week's order log (full export incl. Auto Bill Pay / plan
# add-ons + the Tiered Volume bonus in the Week Total) and replies with the
# board image in the day's 5:10 thread in #a-players-b2b (Carlos 2026-08-30).
#
# CADENCE: 05:20 / 05:50 / 06:30 — after the 5:10 sales-boards post creates
# the thread. The module HOLDS (exit 75) while the export lacks the target
# day or the thread doesn't exist yet; the dedup on 'Revenue Board <tag>'
# makes repeat passes post-once. Pull takes the shared CDP lock (same as
# att_order_log / captainship_boards) and waits its turn.
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.vantura_revenue_board.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-revenue-board SKIPPED — previous pass still running"
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

MODE="--post"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/vantura-revenue-board-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] vantura-revenue-board starting (mode: ${MODE:-dry})" > "$LOG_FILE"

if [ "${1:-}" != "--dry" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('vantura_revenue_board','Revenue Board -> thread')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.vantura_revenue_board.run $MODE >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] vantura-revenue-board finished exit=$ST" >> "$LOG_FILE"

if [ "${1:-}" != "--dry" ]; then
    case "$ST" in
        0)  _PUB=success ;;
        75) _PUB=partial ;;
        *)  _PUB=failed  ;;
    esac
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_revenue_board','Revenue Board -> thread','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit 0
