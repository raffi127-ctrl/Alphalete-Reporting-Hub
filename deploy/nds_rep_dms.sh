#!/bin/bash
# Each NDS rep's own order-log picture to them on Slack, and EVERY rep's
# picture to Carlos and Sebastian (Carlos 2026-11-23: "every morning send the
# reps the updated order log at 9am. send sebastian and i alll of them").
# Fired by launchd on LUCY 2 every day: com.alphalete.nds-rep-dms at 9:00,
# plus a 9:20 tick that only retries what failed (--daily keeps a once-a-day
# state per person per picture).
#
# Who gets what = the 'NDS Rep Slack IDs' tab on the control sheet (key ALL =
# every picture; any other key = one rep's name words, e.g. jacob_ortega).
# A new rep = one new row there; nothing here changes.
#
#   bash deploy/nds_rep_dms.sh --dm-reps-dry     # DRY RUN: who would get what
#
# See automations/nds_metrics/rep_order_log.py (send_shots).

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nds-rep-dms-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] nds rep order-log DMs starting (extra args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.nds_metrics.run --rep-shot active --dm sheet --dm-reps sheet --daily "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] nds rep order-log DMs done (exit $rc)" >> "$LOG_FILE"
exit $rc
