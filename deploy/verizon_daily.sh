#!/bin/bash
# Verizon daily metrics (Nico) — Credico's Sales Verification from the Hub
# inbox -> sales board image + the NDS wireless boards into the day's
# "Verizon Metrics" thread in #alphalete-gp-sales. Fired by launchd
# (com.alphalete.verizon-daily) on LUCY 4 at 11:15 / 11:45 / 12:30 / 13:30 / 14:30 / 15:30 / 17:00 (Sundays land ~2:10 PM);
# daily.py posts ONCE a day, the first time today's file is in.
#
#   bash deploy/verizon_daily.sh            # PREVIEW, sends nothing
#   bash deploy/verizon_daily.sh --send     # post
#
# See automations/verizon_office/daily.py.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/verizon-daily-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] verizon daily starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.verizon_office.daily --office nicolas "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] verizon daily done (exit $rc)" >> "$LOG_FILE"
exit $rc
