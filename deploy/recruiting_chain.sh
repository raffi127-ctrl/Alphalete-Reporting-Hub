#!/bin/bash
# Recruiting chain — run the dashboard's AppStream reports back-to-back, in
# dependency order, instead of on independent timers (Carlos 2026-08-29).
#
# WHY A CHAIN. funnel_board, indeed_source_report and ad_sales_board all log
# into AppStream and all write the Alphalete Recruiting Dashboard. On separate
# timers they overlapped, fought for the AppStream session, and (with the
# resume pusher also logging in) tripped Cloudflare. Running them in sequence
# means each starts when the previous one has actually FINISHED — no guessing
# at durations, and only one AppStream login at a time.
#
#   1am chain:  funnel_board -> indeed_source_report -> ad_sales_board
#   1pm chain:  indeed_source_report -> ad_sales_board
#
# Usage:  bash deploy/recruiting_chain.sh full       # all three (1am)
#         bash deploy/recruiting_chain.sh refresh    # indeed + ad sales (1pm)
#         bash deploy/recruiting_chain.sh full --dry-run
#
# TIME KNOB: edit StartCalendarInterval in
#   deploy/com.alphalete.recruiting-chain-1am.plist   (01:00)
#   deploy/com.alphalete.recruiting-chain-1pm.plist   (13:00)
# then re-install:
#   python -m automations.day_orchestrator.install_agent recruiting-chain-1am
set -u
cd "$(dirname "$0")/.." || exit 1

MODE="${1:-full}"
shift 2>/dev/null || true
EXTRA=("$@")

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/recruiting-chain-$(date +%Y%m%d-%H%M%S).log"

# Overlap guard: the 1pm chain must never start while the 1am one is somehow
# still going, and a manual run must not fight a scheduled one.
if pgrep -f "deploy/recruiting_chain.sh" | grep -qv "^$$\$"; then
    echo "[$(date)] recruiting-chain SKIPPED — a previous chain is still running" | tee -a "$LOG"
    exit 0
fi

case "$MODE" in
  full)    STEPS=("funnel_board_hourly.sh" "indeed_source_report.sh" "ad_sales_board.sh") ;;
  refresh) STEPS=("indeed_source_report.sh" "ad_sales_board.sh") ;;
  *) echo "unknown mode '$MODE' (want: full | refresh)" | tee -a "$LOG"; exit 2 ;;
esac

echo "[$(date)] recruiting-chain START mode=$MODE steps=${#STEPS[@]}" | tee -a "$LOG"
FAILED=()
for s in "${STEPS[@]}"; do
    echo "[$(date)] --> $s" | tee -a "$LOG"
    START=$(date +%s)
    if [ "${#EXTRA[@]}" -gt 0 ]; then
        bash "deploy/$s" "${EXTRA[@]}" >> "$LOG" 2>&1
    else
        bash "deploy/$s" >> "$LOG" 2>&1
    fi
    RC=$?
    echo "[$(date)] <-- $s exit=$RC ($(( $(date +%s) - START ))s)" | tee -a "$LOG"
    # Keep going on failure: skipping the rest would silently cost a whole day
    # of data on reports that do not depend on each other's success.
    [ $RC -ne 0 ] && FAILED+=("$s")
done

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "[$(date)] recruiting-chain FINISHED with ${#FAILED[@]} failure(s): ${FAILED[*]}" | tee -a "$LOG"
    exit 1
fi
echo "[$(date)] recruiting-chain FINISHED clean" | tee -a "$LOG"
exit 0
