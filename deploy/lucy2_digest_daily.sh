#!/bin/bash
# Lucy 2's daily "what ran" summary — but generated ON LUCY 1.
# (com.alphalete.lucy2-digest, once per day.) The Hub Activity log is shared, so
# Lucy 1 can summarize Lucy 2's runs by hostname without touching Lucy 2 at all
# — robust even when Lucy 2 is down or on a different branch. Emails "[Lucy 2] …"
# to the same inbox as Lucy 1's summary. Quiet on days Lucy 2 ran nothing.
#
#   bash deploy/lucy2_digest_daily.sh --dry-run   # build the .eml, don't send
#
# --host matches Lucy 2's hostname as a substring (tolerant of .local vs
# .attlocal.net). If Carlos's mini is ever renamed, update the value here.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/lucy2-digest-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

"$VENV_PY" -m automations.machine_digest.run \
  --host "Mac.attlocal.net,Carloss-Mac-mini-2" --label "Lucy 2" "$@" >> "$LOG_FILE" 2>&1
ST=$?
if [ "$ST" -ne 0 ]; then
  echo "[$(date)] lucy2-digest exit=$ST" >> "$LOG_FILE"
  osascript -e "display notification \"Lucy 2 digest failed (exit $ST)\" with title \"Hub\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
