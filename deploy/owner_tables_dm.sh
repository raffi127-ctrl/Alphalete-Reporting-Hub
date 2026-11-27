#!/bin/bash
# The owners' churn table + week-ending activation table to Carlos's Slack DM,
# every morning. Carlos 2026-11-27: "send me the churn and activation report
# everyday". Same two pictures as `lucy rerun nds_metrics_probe --owner-churn
# ... --dm` and `--owner-weeks ... --summary-only --dm` (owner_churn.py /
# owner_weeks.py). Runs on LUCY 1: its Tableau login sees every NDS owner
# (Lucy 2's sees only 5), and Raf's row comes from the D2D order log.
# Fired by launchd com.alphalete.owner-tables-dm at 9:00 every day.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/owner-tables-dm-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

OWNERS="Carlos Hidalgo;Khalil Mansour;Colten Wright;Jairo Ruiz;Rafael Hidalgo"
DM="U046G04P5LG"   # Carlos

echo "[$(date)] owner tables DM starting" >> "$LOG_FILE"
"$VENV_PY" -m automations.nds_metrics.probe --owner-churn "$OWNERS" --dm "$DM" >> "$LOG_FILE" 2>&1
rc1=$?
"$VENV_PY" -m automations.nds_metrics.probe --owner-weeks "$OWNERS" --summary-only --dm "$DM" >> "$LOG_FILE" 2>&1
rc2=$?
echo "[$(date)] owner tables DM done (churn exit $rc1, activation exit $rc2)" >> "$LOG_FILE"
[ $rc1 -eq 0 ] && [ $rc2 -eq 0 ]
