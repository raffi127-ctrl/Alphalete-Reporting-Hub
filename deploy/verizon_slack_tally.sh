#!/bin/bash
# Verizon live sales — read the office's running tally in #alphalete-gp-sales
# (Nico's reps' :drop_of_blood: list) and relay it as office 'nicolas', every
# 5 minutes via launchd (com.alphalete.verizon-slack-tally) on LUCY 4 (Megan:
# not Lucy 1, the most weighed-down machine).
#
#   bash deploy/verizon_slack_tally.sh            # PREVIEW, sends nothing
#   bash deploy/verizon_slack_tally.sh --send     # relay
#
# See automations/verizon_office/slack_tally.py.

set -u
cd "$(dirname "$0")/.." || exit 1

HOUR=$(TZ=America/Chicago date +%H)
HOUR=${HOUR#0}
# 12:00-00:59 Central: sales start ~noon; a late list lands just after midnight.
{ [ "$HOUR" -ge 1 ] && [ "$HOUR" -lt 12 ]; } && exit 0

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/verizon-slack-tally-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] verizon slack tally starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.verizon_office.slack_tally --tick "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] verizon slack tally done (exit $rc)" >> "$LOG_FILE"
exit $rc
