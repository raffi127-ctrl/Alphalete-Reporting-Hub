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

# LIVE since 2026-08-24 (Megan: "Let's just take it live"). Held 8/23 while
# the OV uploader was proven. Re-hold = flip to 0, push, `lucy update`.
HEADSHOTS_LIVE="${HEADSHOTS_LIVE:-1}"
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

# TELL THE HUB (Megan 2026-08-24). Without this the card could only ever read
# "scheduled Mon 08:30, no run logged" — a clean post and a dead agent looked
# identical, and the one thing Megan actually wants flagged (the Monday thread
# failing to start) could never show at all. Megan: "the headshot shouldn't
# error unless there's an issue with just starting the new thread each Monday."
# Publishing under THIS id is what makes that true: success greens the card and
# clears it from Needs attention, a non-zero exit turns it red.
# Best-effort — a Hub hiccup must never fail the post itself.
# [[feedback_launchd_reports_must_publish]]
if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('headshots_monday','Headshots Monday','$_PUB')" >> "$LOG_FILE" 2>&1 || true

exit $ST
