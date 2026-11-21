#!/bin/bash
# Lucy Transcriber — the always-on Slack bot reps DM their pitch recordings to
# (automations/lucy_transcriber/bot.py). Socket Mode, so nothing inbound;
# launchd keeps it alive (com.alphalete.lucy-transcriber, KeepAlive) and
# `exec` lets launchd track the python process directly.
#
# Tokens (never in the repo): ~/.config/recruiting-report/transcriber-bot-token
# (xoxb-) and transcriber-app-token (xapp-). Without them the bot exits 2 and
# launchd retries every 60 s (ThrottleInterval) — harmless until they land.
#
# Hub pill: bot.py publishes only when a transcript is DELIVERED (or a
# recording fails for good), never from this wrapper.
#
# Needs: an Apple-silicon Lucy (mlx-whisper) and the Anthropic key.
# Check the box first:  .venv/bin/python -m automations.lucy_transcriber.run --doctor --fix
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick up pushed fixes on each (re)start.
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
export PYTHONPATH="$(pwd)"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_COLOR=1
mkdir -p output/logs
exec "$VENV_PY" -u -m automations.lucy_transcriber.bot >> "output/logs/lucy-transcriber-bot.log" 2>&1
