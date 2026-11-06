#!/bin/bash
# Verizon house feed — read a Verizon office's Optix on this machine and relay it
# under the office's key, until their own ECO machine relays (Megan 2026-11-06,
# Nico Murrugarra, on MEGAN'S LAPTOP). Every 5 minutes via launchd
# (com.alphalete.verizon-house-feed).
#
#   bash deploy/verizon_house_feed.sh            # PREVIEW, sends nothing
#   bash deploy/verizon_house_feed.sh --send     # relay
#
# See automations/verizon_office/house_feed.py.

set -u
cd "$(dirname "$0")/.." || exit 1

HOUR=$(TZ=America/Chicago date +%H)
HOUR=${HOUR#0}
# 10:00-21:59 Central (Grand Prairie TX). Off-hours ticks cost a few ms here.
{ [ "$HOUR" -lt 10 ] || [ "$HOUR" -gt 21 ]; } && exit 0

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/verizon-house-feed-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] verizon house feed starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.verizon_office.house_feed --office nicolas "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] verizon house feed done (exit $rc)" >> "$LOG_FILE"
exit $rc
