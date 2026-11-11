#!/bin/bash
# Interviewers Retention -- the two podiums by email, every day at 6 PM CENTRAL
# (Camila, 2026-11-11), to Raf, Perla and Camila, sent from Camila's Gmail.
#
# Runs on CAMILA'S MAC: her Gmail app password lives there
# (~/.config/recruiting-report/camila-gmail-app-password).
# launchd fires every hour on the local clock; the module's --scheduled gate
# sends only in the 18:00 Central hour, once a day, whatever zone the Mac is on.
#
#   bash deploy/interviewers_retention.sh              # the scheduled pass
#   bash deploy/interviewers_retention.sh --dry-run    # now, send nothing

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/interviewers-retention-$(date +%Y-%m-%d).log"
echo "[$(date)] interviewers-retention starting (args: $*)" >> "$LOG_FILE"

if [ $# -eq 0 ]; then
  "$VENV_PY" -m automations.interviewers_retention.run --scheduled --production >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -m automations.interviewers_retention.run "$@" >> "$LOG_FILE" 2>&1
fi
ST=$?
echo "[$(date)] interviewers-retention finished exit=$ST" >> "$LOG_FILE"
exit $ST
