#!/bin/bash
# Daily "what ran on this machine" summary — one launchd fire per day
# (com.alphalete.machine-digest). Reads the shared Hub Activity tab filtered to
# THIS machine's hostname and emails a summary, matching Lucy 1's daily report
# summary. Intended for Lucy 2 (Lucy 1 already gets the orchestrator's final).
#
#   bash deploy/machine_digest_daily.sh --dry-run   # build the .eml, don't send
#
# Quiet by design: sends nothing on days this machine ran nothing.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/machine-digest-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

"$VENV_PY" -m automations.machine_digest.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
if [ "$ST" -ne 0 ]; then
  echo "[$(date)] machine-digest exit=$ST" >> "$LOG_FILE"
  osascript -e "display notification \"Machine digest failed (exit $ST)\" with title \"Hub\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
