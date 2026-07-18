#!/bin/bash
# SaraPlus-down escalation — polls #sara-down every 5 min on the always-on Mac
# mini via launchd (com.alphalete.sara-down). For each NEW screenshot posted by
# an approved leader, emails the DSI/SaraPlus team with the photo attached.
#
#   bash deploy/sara_down_5min.sh --dry-run   # preview the email, send nothing
#
# Runs 24/7 (no daytime gate) — outages at night are the whole point.
# Pure Slack API + Gmail SMTP: no Sheet writes, no session holder, no browser.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"   # fall back to system python if no venv

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sara-down-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] sara-down starting (extra args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.sara_down.run "$@" >> "$LOG_FILE" 2>&1
echo "[$(date)] sara-down done (exit $?)" >> "$LOG_FILE"
