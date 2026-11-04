#!/bin/bash
# 2nd round retention per office — HOURLY feed for Camila's dashboard
# (Eve, 2026-10-29). RUNS ON LUCY 1 (has the drive-full-reporting token the
# write uses). Reads AppStream Retention - Details (new) for every office and
# rewrites this week's rows in the "2nd Round Retention por Oficina" sheet.
# A full pass takes ~25 min (≈170 offices).
#
# TIME KNOB: StartCalendarInterval in com.alphalete.second-round-retention-hourly.plist
#
# Manual test:  bash deploy/second_round_retention_hourly.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.second_round_retention.run" > /dev/null 2>&1; then
    echo "[$(date)] second-round-retention SKIPPED — previous pass still running"
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
# NOTE: no HEADLESS=1 — headless trips a Cloudflare re-challenge on the AppStream login.

LOG_FILE="$LOG_DIR/second-round-retention-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] second-round-retention starting: $*" > "$LOG_FILE"

CMD=("$VENV_PY" -u -m automations.second_round_retention.run)
if [ "$#" -gt 0 ]; then
    CMD+=("$@")
fi
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] second-round-retention finished exit=$ST" >> "$LOG_FILE"
exit 0
