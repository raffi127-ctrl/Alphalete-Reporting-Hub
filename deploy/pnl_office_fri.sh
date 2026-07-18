#!/bin/bash
# PNL for the Office — weekly Friday Slack post, AS LUCY, on the mini.
# launchd fires passes 10:00-12:55 CST every Friday, q25m; the module's fill-gate
# holds (exit 75) until the previous completed week's column is non-zero, then
# posts once to #top-leaders-alphalete-org + #alphalete-lvl1-chat. A per-week
# state file makes the later passes no-ops.
#
# CADENCE: Fridays only (Weekday 5 in the plist). TIME KNOB: edit
# StartCalendarInterval in deploy/com.alphalete.pnl-office-fri.plist, not here.
#
# Manual test (dry-run, no post):  bash deploy/pnl_office_fri.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.pnl_office.run" > /dev/null 2>&1; then
    echo "[$(date)] pnl-office SKIPPED — previous pass still running"
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

# LIVE by default (--post). Pass "--dry" to this wrapper to force a dry-run.
MODE="--post"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/pnl-office-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] pnl-office starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.pnl_office.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 75 = fill-gate held (target week not filled yet) — expected; next pass retries.
echo "[$(date)] pnl-office finished exit=$ST" >> "$LOG_FILE"
exit 0
