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

# HUB PILL. The chain is one card ("Recruiting Chain") that colours in two
# PHASES: amber after the 1am chain, green after the 1pm refresh. Both passes
# publish under the SAME report id, with DIFFERENT names -- the card is
# phase_runs, which counts DISTINCT names, so re-running the 1am chain counts
# once and can never tick the afternoon's box.
#
# Before this the wrapper published nothing at all. The steps each published
# their own run, but the chain itself was invisible, so hub_coverage auto-carded
# the two PLISTS instead and the Hub carried two permanently-white cards reading
# "scheduled 1:00 AM, no run logged" every day while the chain ran perfectly
# (Megan 2026-09-01: "recruiting chain is on here twice? also erroring").
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
case "$MODE" in
  full)    PHASE_NAME="Recruiting Chain - 1 AM full (funnel > indeed > ad sales)" ;;
  refresh) PHASE_NAME="Recruiting Chain - 1 PM refresh (indeed > ad sales)" ;;
esac
# A --dry-run rehearsal publishes nothing: it delivered no data, and a green
# pill for a rehearsal is the same lie as a green pill for a skipped run.
PUBLISH=1
case " ${EXTRA[*]:-} " in *" --dry-run "*) PUBLISH=0 ;; esac

_publish() {  # _publish <status>
    [ "$PUBLISH" -eq 1 ] || return 0
    "$VENV_PY" -c "import sys
from automations.day_orchestrator import hub_publish
hub_publish.publish_done('recruiting_chain', sys.argv[1], sys.argv[2])" \
        "$PHASE_NAME" "$1" >> "$LOG" 2>&1 || true
}

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
    _publish failed
    exit 1
fi
echo "[$(date)] recruiting-chain FINISHED clean" | tee -a "$LOG"
_publish success
exit 0
