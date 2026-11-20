#!/bin/bash
# 2nd rounds & new starts report (automations/second_round_report), run by a
# launchd agent with its arguments -- e.g. com.alphalete.second-round-cards-1120
# (Carlos 2026-11-19: the 4-week cards to NEW A Players on Fri 11/20, 9:00 AM).
#
#   bash deploy/second_round_report.sh --view weeks --weeks 4 --through 2026-11-18 --cards-only   # picture only
set -u
cd "$(dirname "$0")/.." || exit 1
VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/second-round-report-$(date +%Y-%m-%d).log"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
echo "[$(date)] second round report starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.second_round_report.run "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] second round report done (exit $rc)" >> "$LOG_FILE"
exit $rc
