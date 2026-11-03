#!/bin/bash
# Monday 8:45, 8:55 + 9:00pm CT: Leader's Call countdown posts to
# #top-leaders-alphalete-org + #alphalete-gp-sales AS Lucy, on the always-on Mac
# mini via launchd (com.alphalete.leaders-call-reminders). The plist passes --send;
# without it this is a dry-run.
#
#   bash deploy/leaders_call_reminders.sh --slot 15   # preview that message, no post

set -u
cd "$(dirname "$0")/.." || exit 1

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

LOG_FILE="$LOG_DIR/leaders-call-reminders-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Leader's Call reminder starting (args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.leaders_call.reminders "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Leader's Call reminder finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Leader's Call reminder failed (exit $ST) — is Lucy a member of the channel?\" with title \"Leader's Call\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
