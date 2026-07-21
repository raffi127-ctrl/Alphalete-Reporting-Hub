#!/bin/bash
# Sunday morning — create the coming week's tab in Maud's "Alphalete Recognition"
# sheet (a copy of the LUCY TEMPLATE tab, named by the week-ending Sunday, e.g.
# 7.26.26) so ICDs have a fresh tab to log office promotions BEFORE Maud's Monday
# reminder goes out. Runs on the always-on Mac mini via launchd
# (com.alphalete.recognition-tab-sun).
#
# Idempotent: if the week's tab already exists it does nothing. It only ADDS a tab
# (duplicates the template) — it never edits, clears, or deletes any tab.
#
#   bash deploy/recognition_tab_sun.sh --dry-run   # read-only, print the plan
#
# Needs on the machine: ~/.config/recruiting-report OAuth token (Sheets access to
# the recognition sheet). See automations/leaders_call/recognition_tab.py.

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

LOG_FILE="$LOG_DIR/recognition-tab-sun-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] recognition tab create starting (extra args: ${*:-none})" > "$LOG_FILE"

# Default to --write; any extra arg (e.g. --dry-run) is appended and wins.
"$VENV_PY" -u -m automations.leaders_call.recognition_tab --write "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] recognition tab create finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Recognition weekly tab create failed (exit $ST)\" with title \"Recognition Tab\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
