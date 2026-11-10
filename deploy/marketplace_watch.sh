#!/bin/bash
# Marketplace Watch — email Megan new cheap/free office furniture listed on
# Facebook Marketplace within ~20 min of the office. 9am + 3pm, max 2 a day.
#
# RUNS ON MEGAN'S LAPTOP ONLY: the Facebook sign-in lives in this machine's
# automations/marketplace_watch/.browser_profile_fb. Signed out? Run:
#   python -m automations.marketplace_watch.run --login
#
# Manual dry test (prints the email, sends nothing):
#   bash deploy/marketplace_watch.sh
# Real send:
#   bash deploy/marketplace_watch.sh --send
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.marketplace_watch.run" > /dev/null 2>&1; then
    echo "[$(date)] marketplace-watch SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/marketplace-watch-$(date +%Y-%m-%d).log"
echo "[$(date)] marketplace-watch starting: $*" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.marketplace_watch.run "$@" >> "$LOG_FILE" 2>&1
# Captured before any $(date): a subshell in between would clobber the status.
ST=$?

echo "[$(date)] marketplace-watch finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
