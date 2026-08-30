#!/bin/bash
# Vantura Sales Board morning close-out from the ORDER LOGS, on LUCY 2.
# Reads "Lucy At&t Data" (+ "Lucy Box Data" from the 2026-09-01 cutover) and
# writes yesterday's day column on the "Sales Board" tab — the authoritative
# close-out Carlos asked for 2026-08-30 ("this morning you would have looked
# at yesterday's order log and filled in the proper sales").
#
# CADENCE: 05:02 daily incl. weekends. AFTER the 4am batch's att_order_log
# refresh and the 05:00 vantura-slack-sales close-out (both raise-only, so
# order never changes a number the other one raised), and BEFORE
# com.alphalete.sales-boards' 05:10 post, which renders whatever is on the
# board. Pure Sheets API — no Tableau, no browser, safe at any hour.
#
# NO BACKFILL of days before 2026-08-31: Carlos hand-spread some earlier
# sales across days on purpose ("I knew what their total should be",
# 2026-08-30) — a raise-only backfill would double-count those weeks. The
# module's no---date default (yesterday) is exactly right; never add --week
# to this wrapper.
#
# Manual test (no writes):  bash deploy/vantura_orderlog_sales.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.vantura_orderlog_sales.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-orderlog-sales SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/vantura-orderlog-sales-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] vantura-orderlog-sales starting (mode: $MODE)" > "$LOG_FILE"

if [ "${1:-}" != "--dry" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('vantura_orderlog_sales','Sales Board Fill (order log)')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.vantura_orderlog_sales.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] vantura-orderlog-sales finished exit=$ST" >> "$LOG_FILE"

# Done-marker + Hub pill, same contract as vantura_slack_sales.sh: marker =
# "a pass ran today"; the Hub card is how a silent launchd miss gets seen.
# exit 75 = wrong-week HOLD (nothing written, correct behaviour) -> amber.
if [ "${1:-}" != "--dry" ]; then
    touch "$LOG_DIR/.vantura-orderlog-sales-done-$(date +%Y-%m-%d)"
    find "$LOG_DIR" -name ".vantura-orderlog-sales-done-*" -mtime +3 -delete 2>/dev/null
    case "$ST" in
        0)  _PUB=success ;;
        75) _PUB=partial ;;
        *)  _PUB=failed  ;;
    esac
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_orderlog_sales','Sales Board Fill (order log)','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit 0
