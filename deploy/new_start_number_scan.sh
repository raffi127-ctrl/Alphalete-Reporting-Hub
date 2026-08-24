#!/bin/bash
# New-start NUMBER SCAN — hourly weekend check of the "numbers needed" post.
#
# When the Saturday 8:30 texts find leaders with no phone number, Lucy posts a
# numbered list in the week's thread tagging Raf + Aisha. ANYONE can reply with
# "Name - number" (or "Name - terminated"). This job re-reads those replies
# every hour, and when a number has arrived Lucy saves it, texts that leader,
# and replies "Got it - texted ..." in the thread.
#
# It does NOT run the scan itself: sending an iMessage needs macOS's
# control-Messages permission, which only the mini_control POLLER identity
# holds (same lesson as b2b_dispositions on Lucy 2). So this script just drops
# a `rerun new_start_number_replies` row on this machine's own control queue;
# the poller picks it up within ~2 minutes and does the actual work. The scan
# is idempotent (per-week/per-leader sent markers), so hourly re-runs are safe.
#
# Runs on Lucy 1 via launchd:
#   com.alphalete.new-start-number-replies   Sat + Sun, hourly 9am-6pm Central

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
export PYTHONPATH="$(pwd)"
export NO_COLOR=1

"$VENV_PY" -m automations.day_orchestrator.mini_control \
  --by "Number Scan" --enqueue rerun new_start_number_replies
