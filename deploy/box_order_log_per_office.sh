#!/bin/bash
# BOX Order Log, one Slack thread per ONBOARDED office (automations.box_order_log
# .per_office). RUNS ON THE MINI (Lucy 1): its Tableau session sees every Box
# owner org-wide; Lucy 2's is scoped to Carlos. Sibling of box_order_log_owners.sh
# (which EMAILS the manual owners.py registry) -- same two passes, 7:00 with
# --require-fresh and 8:30 without, and exactly ONE post per day: a dated marker
# is written after a successful pass, so 8:30 skips a day 7:00 already posted.
# First office: Ryan McSpadden, 2026-10-09 (Megan: "wire up Ryan McSpadden's
# metrics and trackers"). `--dry` builds everything and posts nothing.
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.box_order_log.per_office" > /dev/null 2>&1; then
    echo "[$(date)] box-order-log-per-office SKIPPED — previous pass still running"
    exit 0
fi

if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
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

DRY=""
[ "${1:-}" = "--dry" ] && DRY="1"
MARKER="$LOG_DIR/.box-order-log-per-office-posted-$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/box-order-log-per-office-$(date +%Y-%m-%d-%H%M%S).log"

if [ -n "$DRY" ]; then
    MODE=""
elif [ -f "$MARKER" ]; then
    echo "[$(date)] already posted today — skipping" >> "$LOG_FILE"
    exit 0
else
    MODE="--post"
    if [ "$(date +%H)" -lt 8 ]; then
        MODE="$MODE --require-fresh"
    fi
fi

echo "[$(date)] box-order-log-per-office starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"
"$VENV_PY" -u -m automations.box_order_log.per_office $MODE >> "$LOG_FILE" 2>&1
ST=$?
if [ -n "$DRY" ]; then
    echo "[$(date)] dry-run done (exit $ST)" >> "$LOG_FILE"
elif [ "$ST" -eq 0 ]; then
    touch "$MARKER"
    echo "[$(date)] posted; marker written" >> "$LOG_FILE"
    find "$LOG_DIR" -name ".box-order-log-per-office-posted-*" -mtime +3 -delete 2>/dev/null
elif [ "$ST" -eq 3 ]; then
    echo "[$(date)] extract not fresh — deferred to the 8:30 pass" >> "$LOG_FILE"
else
    echo "[$(date)] FAILED (exit $ST) — marker left unset so the later pass retries" >> "$LOG_FILE"
fi
echo "[$(date)] box-order-log-per-office finished exit=$ST" >> "$LOG_FILE"
exit $ST
