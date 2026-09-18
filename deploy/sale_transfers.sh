#!/bin/bash
# EVERY DAY 05:00: move yesterday's 'ATT Sales Transfers' form sales on the
# Alphalete Sales Board, on Lucy 1 via launchd (com.alphalete.sale-transfers).
#
# WHY THIS LEFT THE ORCHESTRATOR (Eve 2026-09-18). sales_board_sale_transfers
# sat in the 4am pass with no `order`, so it sorted LAST, and its
# `not_before 05:00` is only a floor, never a start time. On 9/18 the pass was
# still on fiber_activations at 07:35 CT with the transfers `pending`; Eve had
# to move 9/17's sales by hand. A clock cannot be starved by the queue in
# front of it. Eve: "que corra a las 5".
#
# ONCE PER SALE, NOT PER DAY. sale_transfers keeps its own record of every
# moved form row (~/.config/recruiting-report/sale_transfers_state.json, plus
# the checked-in sale_transfers_hand_done.json for sales a person moved), so
# the 06:00 / 08:00 safety slots only move forms that came in late at night --
# never the same sale twice. The record is per machine: this runs on Lucy 1
# ONLY.
#
# Manual:  bash deploy/sale_transfers.sh --dry     (preview, writes nothing)
#          lucy rerun sales_board_sale_transfers   (same move, from the queue)
set -u
cd "$(dirname "$0")/.." || exit 1

# Fresh code first: this wrapper is the only thing that runs the module on a
# schedule, so without its own pull a pushed fix would wait for a `lucy update`.
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/sale-transfers-$(date +%Y-%m-%d-%H%M%S).log"

# Two passes on the board at once could both read the same "before" values.
if pgrep -f "automations.alphalete_sales_board.sale_transfers" > /dev/null 2>&1; then
    echo "[$(date)] SKIPPED -- a sale_transfers run is still going" > "$LOG_FILE"
    exit 0
fi

APPLY="--apply"
[ "${1:-}" = "--dry" ] && APPLY=""

echo "[$(date)] sale transfers starting (${APPLY:-preview})" > "$LOG_FILE"
"$VENV_PY" -u -m automations.alphalete_sales_board.sale_transfers $APPLY >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] sale_transfers exit=$ST" >> "$LOG_FILE"

# A failed slot has a retry behind it; alert only on the LAST one (08:00).
if [ "$ST" -ne 0 ] && [ -n "$APPLY" ] && [ "$(date +%H%M)" -ge "0800" ]; then
    "$VENV_PY" -u -c "
import datetime as dt, sys
from automations.day_orchestrator import registry as _reg, notify
notify.send_standalone_alert(
    _reg.load_config(), name='Sales Board - sale transfers',
    report_id='sales_board_sale_transfers', kind='FAILED',
    status='the form transfers were not moved (exit ' + sys.argv[1] + ')',
    when='morning sale transfers (05:00-08:00)',
    day=dt.date.today().isoformat(), machine_label='Lucy 1')
" "$ST" >> "$LOG_FILE" 2>&1 || true
fi
exit $ST
