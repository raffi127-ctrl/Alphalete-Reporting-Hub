#!/bin/bash
# Weekly Promotion Check-In — post the interactive card to #alphalete-lvl1-chat.
# Two launchd jobs use this: com.alphalete.promo-checkin-mon (Mon 6:00pm CST) and
# com.alphalete.promo-checkin-final (Mon 7:15pm, passes --final-call).
#
# Posting the card writes NOTHING to any sheet — the sheet is only touched when a
# leader clicks "Log promotions", handled by the always-on Jiraiya listener
# (com.alphalete.jiraiya-bot). So this job is safe to re-run.
#
# Manual test (DM the preview card to Megan, never writes):
#   bash deploy/promotion_checkin_post.sh --dm Megan
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/promo-checkin-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Promotion Check-In post starting (args: ${*:-none})" > "$LOG_FILE"

# Default action is --post (live channel); extra args (e.g. --final-call / --dm)
# are appended. If any --dm/--post/--final-call already present, "$@" carries it.
if printf '%s\n' "$@" | grep -qE -- '--dm|--post'; then
  "$VENV_PY" -u -m automations.promotion_checkin.run "$@" >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -u -m automations.promotion_checkin.run --post "$@" >> "$LOG_FILE" 2>&1
fi
ST=$?
echo "[$(date)] Promotion Check-In finished exit=$ST" >> "$LOG_FILE"
exit 0
