#!/bin/bash
# New-start THREAD SCAN — answers people who @-tag Lucy in the week's thread.
#
# Raf asked to be able to talk to Lucy by tagging her (2026-08-30). This job
# checks the thread for replies mentioning her that haven't been answered yet.
# Most firings find nothing and cost one Slack read: the roster OCR is cached
# per screenshot file, and no model is called unless there is an actual new
# question.
#
# It does NOT do the work itself. It drops a `rerun new_start_thread_replies`
# row on this machine's own control queue and the POLLER runs it, the same
# pattern as the number scan next to it — one identity does the work, so
# permissions and logging stay in one place. Answering is idempotent (per
# mention timestamp, per week), so re-runs are safe.
#
# Runs on Lucy 1 via launchd:
#   com.alphalete.new-start-thread-replies   every day, every 30 min, 8am-8pm

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
export PYTHONPATH="$(pwd)"
export NO_COLOR=1

"$VENV_PY" -m automations.day_orchestrator.mini_control \
  --by "Thread Scan" --enqueue rerun new_start_thread_replies
