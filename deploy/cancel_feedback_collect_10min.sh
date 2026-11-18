#!/bin/bash
# Cancel/disconnect feedback — reply collector, every 10 min on Lucy 4 via
# launchd (com.alphalete.cancel-feedback-collect). Reads inbound SMS on Dylan's
# RC line, matches them to customers we texted, and logs the written feedback
# (flagging STOP opt-outs) to the "Cancel Feedback - Responses" tab. The DAILY
# job (day_orchestrator, 13:00) does the SENDING; this does only the READING
# back, on the same 10-min cadence as the wrap-up auto-read.
#
#   bash deploy/cancel_feedback_collect_10min.sh            # collect + log (live)
# For a dry probe, call the module directly (this wrapper bakes in --live):
#   .venv/bin/python -m automations.cancel_feedback.run --collect-responses
#
# Reading inbound has no TCPA quiet-hours restriction; the window gate below just
# mirrors the auto-read's 7AM-midnight CST active window (the box is Central).
# Needs cancel-feedback-rc-creds.json on this machine (same as the daily send).

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# One log file per day; every 10-min run appends to it.
LOG_FILE="$LOG_DIR/cancel-feedback-collect-$(date +%Y-%m-%d).log"

# ---- WINDOW GATE: only run 7:00 AM-midnight CST (delete block for 24/7) ----
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

# --live makes it actually LOG replies (the module defaults to dry-run). Extra
# args (e.g. --since) pass through; don't pass --dry-run here (mutually exclusive).
echo "[$(date)] cancel-feedback collect starting (extra args: ${*:-none})" >> "$LOG_FILE"

"$VENV_PY" -m automations.cancel_feedback.run --collect-responses --live "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] cancel-feedback collect finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Cancel-feedback reply collect failed (exit $ST)\" with title \"RingCentral\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
