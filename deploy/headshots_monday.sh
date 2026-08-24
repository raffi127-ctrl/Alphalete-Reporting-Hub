#!/bin/bash
# Monday headshot thread-starter — posts Lucy's "Headshot Submissions" thread
# in #11280-alphalete-marketing-inc-rafael-hidalgo (Megan approved the exact
# wording 2026-08-23). Idempotent: the module checks the channel for this
# week's marker post before sending, and posts only on Mondays — so launchd
# retries / manual reruns can never double-post.
# Runs on the always-on Mac mini via launchd (com.alphalete.headshots-monday).
#
#   bash deploy/headshots_monday.sh   # live; safe any day (no-op off-Monday)
#
# Needs on the machine: the Lucy Slack user token (shared slack_metrics_post).
set -u
cd "$(dirname "$0")/.." || exit 1

# HELD until the flow works end to end INCLUDING the OwnerVille profile
# upload (Megan 2026-08-23: "hold off on having a live post until we've got
# it done end to end"). Go-live = flip to 1, push, `lucy update` — same
# pattern as the owner-showdown hold.
HEADSHOTS_LIVE="${HEADSHOTS_LIVE:-0}"
if [ "$HEADSHOTS_LIVE" != "1" ]; then
    echo "[$(date)] headshots-monday HELD (HEADSHOTS_LIVE=0) — not posting"
    exit 0
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/headshots-monday-$(date +%Y-%m-%d).log"
echo "[$(date)] Monday headshot thread starting" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.headshots.weekly_thread >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] finished exit=$ST" >> "$LOG_FILE"
exit $ST
