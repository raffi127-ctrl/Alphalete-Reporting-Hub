#!/bin/bash
# Hourly resume-push report DM (Carlos, 2026-09-24). RUNS ON LUCY 2.
# Sheets + Slack only — no browser. See automations/push_report/run.py.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)"
export NO_COLOR=1

if pgrep -f "automations.push_report.run" > /dev/null 2>&1; then
    echo "[$(date)] push_report SKIPPED — previous pass still running"
    exit 0
fi

LOG_FILE="$LOG_DIR/push-report-$(date +%Y-%m-%d).log"
echo "[$(date)] push_report starting" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.push_report.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] push_report finished exit=$ST" >> "$LOG_FILE"
exit $ST
