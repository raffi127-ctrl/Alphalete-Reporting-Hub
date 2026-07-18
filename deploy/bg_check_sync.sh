#!/bin/bash
# BG-check sync — reads First Advantage/Sterling emails from raffi127@gmail.com,
# updates col K "BG Status" on both D2D OBCL tabs, and posts/edits the weekly
# #rafs-office-recruiting thread as Lucy. Light: no Tableau / no AppStream / no
# browser — safe to run any time, several times a day.
# Runs on the always-on Mac mini via launchd (com.alphalete.bg-check-sync),
# 3x weekday-ish: 8:00 / 11:30 / 16:00 Central. Monday 11:30 is the must-run.
#
#   bash deploy/bg_check_sync.sh --dry-run   # no sheet writes, Slack preview only
#   bash deploy/bg_check_sync.sh             # LIVE (writes + posts) — the default
#
# Needs on the machine:
#   ~/.config/recruiting-report/gmail-app-password-raffi127  (IMAP read)
#   ~/.config/recruiting-report/oauth-token.json             (Sheets write)
#   ~/.config/recruiting-report/slack-bot-token              (post as Lucy)

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# No args = go live (writes + posts). Any args (e.g. --dry-run) pass straight through.
ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--post --since-days 30)

LOG_FILE="$LOG_DIR/bg-check-sync-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] bg-check-sync starting (args: ${ARGS[*]})" > "$LOG_FILE"

"$VENV_PY" -m automations.bg_check_sync.run "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] bg-check-sync finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"BG-check sync failed (exit $ST)\" with title \"BG Check\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
