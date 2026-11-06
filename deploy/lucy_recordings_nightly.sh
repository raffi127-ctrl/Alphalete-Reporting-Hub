#!/bin/bash
# LUCY 2nd round recordings sheet for Raf — DAILY 8:00 AM CT (was 11 PM)
# (Eve, 2026-11-06). RUNS ON LUCY 1: it reads the audit bot's files in
# ~/2nd-rd-audits and writes with the drive-full-reporting token. No AppStream:
# 2nd rounds come from the retention sheet. Takes ~2 min.
#
# TIME KNOB: StartCalendarInterval in com.alphalete.lucy-recordings-nightly.plist
#
# Manual test:  bash deploy/lucy_recordings_nightly.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.lucy_recordings_sheet.run" > /dev/null 2>&1; then
    echo "[$(date)] lucy-recordings SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/lucy-recordings-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] lucy-recordings starting: $*" > "$LOG_FILE"

CMD=("$VENV_PY" -u -m automations.lucy_recordings_sheet.run)
if [ "$#" -gt 0 ]; then
    CMD+=("$@")
fi
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] lucy-recordings finished exit=$ST" >> "$LOG_FILE"
exit 0
