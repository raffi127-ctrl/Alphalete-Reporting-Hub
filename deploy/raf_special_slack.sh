#!/bin/bash
# Raf's AT&T Special Override -> his Slack DM, once per new week (Raf, 2026-11-06).
#
# RUNS ON LUCY 1 (Raf's Tableau login; Slack token posts as Lucy). Every Friday
# (Eve 2026-11-06); retries the same afternoon never double-post.
#
#   bash deploy/raf_special_slack.sh             # dry: prints the message
#   bash deploy/raf_special_slack.sh --preview   # DM to Eve only
#   bash deploy/raf_special_slack.sh --send      # DM to Raf (once per day)
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.raf_special_slack" > /dev/null 2>&1; then
    echo "[$(date)] raf-special-slack SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/raf-special-slack-$(date +%Y-%m-%d).log"
echo "[$(date)] raf-special-slack starting: $*" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.raf_special_slack "$@" >> "$LOG_FILE" 2>&1
# CAPTURED BEFORE ANY $(date) -- a $(...) in between clobbers the exit status.
ST=$?

echo "[$(date)] raf-special-slack finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
