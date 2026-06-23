#!/bin/bash
# 6am daily friendly weather alert for the Frisco team → #alphalete-sales.
# Runs on the always-on Mac mini via launchd (com.alphalete.weather-6am).
# Open-Meteo forecast (no key) + Claude wording + Slack post. Posts just before
# the 7am metrics thread.
#
#   bash deploy/weather_alert_6am.sh --dry-run   # print only, no Slack post
#
# Needs on the machine: ~/.config/recruiting-report/slack-user-token (to post)
# and ~/.config/brand-audit/keys.json (Anthropic key for the nicer wording;
# falls back to a template without it).

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/weather-6am-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] weather alert starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -m automations.weather_alert.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] weather alert finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Weather alert failed (exit $ST)\" with title \"Weather\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
