#!/bin/bash
# Monday recognition reminder → EMAIL to the owners/ICDs, on the always-on Mac mini
# via launchd (com.alphalete.owners-call-reminder), Mon 11:00am, 4:00pm, and 7:15pm
# (final call) CT. The plist passes --send; run without it for a dry-run.
#
#   bash deploy/owners_call_reminder.sh            # dry-run (writes an .eml, no send)
#   bash deploy/owners_call_reminder.sh --send     # actually email
#
# Needs on the machine: the reporting Gmail app password (already used by the other
# report emails) and OWNERS_CALL_EMAILS set to the comma-separated recipient list.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/owners-call-reminder-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] owners-call reminder starting (args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.owners_call_reminder.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] owners-call reminder finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Owners-call reminder failed (exit $ST) — check the group chat id / Messages\" with title \"Owners Reminder\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
