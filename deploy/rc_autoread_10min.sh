#!/bin/bash
# RingCentral wrap-up auto-read — every 10 min on the always-on Mac mini via
# launchd (com.alphalete.rc-autoread). Marks unread SMS read once a thread has
# hit a known wrap-up message; leaves customer-reply threads unread.
#
#   bash deploy/rc_autoread_10min.sh --dry-run   # show what it WOULD mark, no changes
#
# Pure RingCentral API (creds are baked into automations/rc_autoread/run.py).
# No Sheet writes, no Slack, no session holder needed.
#
# CADENCE: the plist fires every 10 min around the clock; this wrapper gates the
# active window to 7:00 AM–midnight CST (the mini is Central, so `date` is CST).
# To run 24/7, delete the WINDOW GATE block below.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# One log file per day; every 10-min run appends to it.
LOG_FILE="$LOG_DIR/rc-autoread-$(date +%Y-%m-%d).log"

# ---- WINDOW GATE: only run 7:00 AM–midnight CST (delete block for 24/7) ----
h=$((10#$(date +%H)))
m=$((10#$(date +%M)))
if ! { [ "$h" -ge 7 ] || { [ "$h" -eq 0 ] && [ "$m" -eq 0 ]; }; }; then
  echo "[$(date)] outside 7AM-midnight CST window (h=$h) — skipping" >> "$LOG_FILE"
  exit 0
fi
# ---------------------------------------------------------------------------

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] rc-autoread starting (extra args: ${*:-none})" >> "$LOG_FILE"

"$VENV_PY" -m automations.rc_autoread.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] rc-autoread finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"RC auto-read failed (exit $ST)\" with title \"RingCentral\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
