#!/bin/bash
# 'Jiraiya' — always-on Socket Mode listener for the /dd popup, on the mini via
# launchd (com.alphalete.jiraiya-bot, KeepAlive). Reads its tokens from
# ~/.config/recruiting-report/dd-bot-token + dd-app-token. `exec` so launchd
# tracks the python process directly and restarts it if it dies.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

exec "$VENV_PY" -u -m automations.due_diligence.bot
