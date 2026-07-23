#!/bin/bash
# Watchdog for bg_check_sync: DMs Raf via Lucy if the report's heartbeat has gone
# stale (i.e. it fell off the scheduler and the OBCL isn't auto-updating).
# Runs on the mini via launchd (com.alphalete.bg-check-watchdog), 12:45 + 17:00 CST.
#
#   bash deploy/bg_check_watchdog.sh --dry-run   # print only, never DM
#
# Needs on the machine: ~/.config/recruiting-report/slack-user-token (Lucy).

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/bg-check-watchdog-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] bg-check watchdog starting (args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -m automations.bg_check_sync.watchdog "$@" >> "$LOG_FILE" 2>&1
echo "[$(date)] bg-check watchdog finished exit=$?" >> "$LOG_FILE"
exit 0
