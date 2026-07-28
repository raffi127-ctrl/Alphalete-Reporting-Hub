#!/bin/bash
# 'Jiraiya' — Due Diligence DM bot, on the mini via launchd
# (com.alphalete.due-diligence-watch). Runs ONE poll of each allowed leader's DM
# with the bot: for a new 'ICD / rep' request, pulls that rep's due-diligence
# numbers from Tableau, replies in the DM, and logs the block to that ICD's tab
# (creating the tab if it's new).
#
# CADENCE: StartInterval in the plist (default 60s = near-instant). Each tick
# does nothing unless a request is waiting, so it's cheap.
#
# GO-LIVE ONLY: this DMs replies + writes the Sheet. Install the plist only
# after Megan confirms go-live. Until then, preview with:
#   .venv/bin/python -m automations.due_diligence.run --once        (no post/write)
#
# Manual live one-shot (DMs!):  bash deploy/due_diligence_watch.sh
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

# Who the bot answers (comma list of ids/emails/names) — REQUIRED.
export DD_DM_USERS="${DD_DM_USERS:-}"
# Jiraiya's own Slack app token (xoxb-…). Unset = fall back to the Lucy bot token.
export DD_BOT_TOKEN="${DD_BOT_TOKEN:-}"
# Guard a stray Chrome on the mini ONLY when a request actually needs Tableau.
export DD_CHROME_GUARD=1

if [ -z "$DD_DM_USERS" ]; then
  echo "[$(date)] DD_DM_USERS not set — refusing to run (would answer no one)." >&2
  exit 2
fi

LOG_FILE="$LOG_DIR/due-diligence-watch-$(date +%Y-%m-%d).log"
# --live posts replies, --write appends to the DD tab. Extra args pass through.
"$VENV_PY" -u -m automations.due_diligence.run --once --live --write "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] due-diligence poll finished exit=$ST" >> "$LOG_FILE"
exit $ST
