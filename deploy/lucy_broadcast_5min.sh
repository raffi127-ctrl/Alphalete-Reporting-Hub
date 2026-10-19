#!/bin/bash
# Lucy Broadcast — polls the broadcast channel every 5 min on Lucy 1 via launchd
# (com.alphalete.lucy-broadcast). Each NEW post is re-sent to the Slack
# channels + iMessage groups in automations/lucy_broadcast/config.py.
#
#   bash deploy/lucy_broadcast_5min.sh --dry-run   # preview, send nothing
#
# Runs 24/7. Pure Slack API + Messages: no Sheet writes, no browser.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"   # fall back to system python if no venv

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/lucy-broadcast-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] lucy-broadcast starting (extra args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.lucy_broadcast.run "$@" >> "$LOG_FILE" 2>&1
# GRAB $? FIRST — the $(date) in the same echo runs before $? is expanded,
# and command substitution RESETS it, so this used to log the status of
# `date` (always 0) instead of the job's. A crashed run read as "exit 0".
# Cost three silent hours on gap_alerts, 2026-09-07.
rc=$?
echo "[$(date)] lucy-broadcast done (exit $rc)" >> "$LOG_FILE"
exit $rc
