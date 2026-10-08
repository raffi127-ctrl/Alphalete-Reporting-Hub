#!/bin/bash
# Raf Guest Orders pull, on LUCY 1 — Carlos's reps sell under RAF's SaraPlus
# code right now (Carlos 2026-10-08, "only selling under Rafs code" until the
# move to his own AT&T NDS code ~a week out). This pulls Raf's Sales Order
# History export with the sales-board sweep's login (Raf's creds + verified
# .saraplus_profile — his account has NO emailed passcode), keeps only the
# guest roster's rows (total_knocks.guests.GUEST_REPS), and base64s them into
# the control sheet's 'Raf Guest Orders' tab for Lucy 2's sp_order_log merge.
#
# CADENCE (plist): 03:45 / 04:15 before Lucy 2's 4am batch needs the rows
# (rc_contact_sync at order 11.5, then b2b_metrics' #8/#9 sections), 06:30
# catch-up, 12:45 so a midday `lucy rerun` merges a same-day pull.
# Idempotent — every pass clears and rewrites the one tab.
# All before 07:00 passes are outside the sweep's selling window, and the
# profile is the sweep's own .saraplus_profile, so the pid guard below is the
# collision guard: never run while the sweep (or a previous pass) holds it.
#
# WHEN THE REPS MOVE to Carlos's own NDS code: unload this agent
# (launchctl bootout gui/$UID/com.alphalete.raf-guest-orders) — the merge on
# Lucy 2 fail-opens past a stale tab on its own, nothing else to edit.
#
# Manual test (filter + report, no sheet write):
#   bash deploy/raf_guest_orders.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.sp_order_log.raf_guest" > /dev/null 2>&1; then
    echo "[$(date)] raf-guest-orders SKIPPED — previous pass still running"
    exit 0
fi
if pgrep -f "automations.alphalete_sales_board.run" > /dev/null 2>&1; then
    echo "[$(date)] raf-guest-orders SKIPPED — the sales-board sweep holds the profile"
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

MODE="--pull"
[ "${1:-}" = "--dry" ] && MODE="--pull --no-upload"

LOG_FILE="$LOG_DIR/raf-guest-orders-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] raf-guest-orders starting (mode: $MODE)" > "$LOG_FILE"

"$VENV_PY" -u -m automations.sp_order_log.raf_guest $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] raf-guest-orders finished exit=$ST" >> "$LOG_FILE"
exit 0
