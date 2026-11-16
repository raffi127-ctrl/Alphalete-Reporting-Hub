#!/bin/bash
# Verizon pictures -> the "Verizon" + "Verizon Leaders" iMessage chats (Carlos
# 2026-11-15). Pulls today's posted PNGs out of #alphalete-gp-sales (the
# tracker thread and the Verizon Metrics thread) and texts what is new. Fired
# by launchd (com.alphalete.verizon-texts) on LUCY 1 through the morning and
# early afternoon; one text per picture per chat per day.
#
#   bash deploy/verizon_texts.sh            # DRY RUN, texts nothing
#   bash deploy/verizon_texts.sh --send     # text
#
# See automations/verizon_office/texts.py.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/verizon-texts-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] verizon texts starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.verizon_office.texts "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] verizon texts done (exit $rc)" >> "$LOG_FILE"
exit $rc
