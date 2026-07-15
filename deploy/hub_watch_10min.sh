#!/bin/bash
# Hub change watcher — every 10 min on the always-on Mac mini via launchd
# (com.alphalete.hub-watch). Emails Megan whenever Hub code/cards change, from
# EITHER path:
#   1. hub_push_watch    — new commits pushed to the repo (code changed directly
#                          from a Claude session, bypassing the Hub).
#   2. hub_library_watch — a card published/edited through the Hub's upload flow
#                          (lands in the shared "Report Library" Google Sheet).
# Both run from the mini because it always has the mail app password + the Sheets
# OAuth token; a teammate's Hub might not.
#
#   bash deploy/hub_watch_10min.sh --dry-run   # build emails, don't send
#   bash deploy/hub_watch_10min.sh --init      # snapshot both, no email
#
# 24/7 (changes can land any time). Cheap: a git fetch + a Sheet read + compares;
# it only emails when something actually moved. The two watchers are independent
# — one failing (network/quota) never blocks the other, and each retries on the
# next run.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/hub-watch-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

FAIL=0

"$VENV_PY" -m automations.hub_push_watch.run    "$@" >> "$LOG_FILE" 2>&1 || FAIL=1
"$VENV_PY" -m automations.hub_library_watch.run "$@" >> "$LOG_FILE" 2>&1 || FAIL=1

if [ "$FAIL" -ne 0 ]; then
  # A watcher hit a transient error (fetch/read/send). State is left untouched
  # so the next run retries; surface it in case it's persistent.
  echo "[$(date)] hub-watch: a watcher exited non-zero (see above)" >> "$LOG_FILE"
  osascript -e "display notification \"Hub watcher hit an error\" with title \"Hub\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
