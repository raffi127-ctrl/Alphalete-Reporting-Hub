#!/bin/bash
# Lucy Transcriber — reps drop a pitch recording in the transcriber channel,
# Lucy replies in the thread with who said what (Rep / Customer). Ticks every
# 2 minutes (com.alphalete.lucy-transcriber.plist). An idle tick is one Slack
# read and exits; the channel id lives in automations/lucy_transcriber/config.py
# and an empty id means "not switched on" (exits before touching Slack).
#
# Hub pill: run.py publishes to the Hub itself, only when a transcript was
# actually DELIVERED (or a recording failed for good) — not from this wrapper,
# because 700 idle ticks a day would each mark the card as "ran".
#
# Needs: an Apple-silicon Lucy (mlx-whisper), Lucy's Slack token with
# files:read, and the Anthropic key. Runs in the background — no window.
#
# Manual:  bash deploy/lucy_transcriber.sh --check --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# One tick at a time (run.py also holds a lock file; this saves the startup).
if pgrep -f "automations.lucy_transcriber.run" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/lucy-transcriber-$(date +%Y%m%d).log"

ARGS=("$@"); [ ${#ARGS[@]} -eq 0 ] && ARGS=(--check)
"$VENV_PY" -m automations.lucy_transcriber.run "${ARGS[@]}" >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "[$(date)] lucy-transcriber rc=$rc" >> "$LOG"
fi
exit $rc
