#!/bin/bash
# Orchestrator heartbeat — runs ~20 min after the 4am orchestrator start and asks
# one question: did it actually produce a day_state today?
#
# Deliberately does NOT `git pull` first. Every other wrapper self-updates, and on
# 2026-08-27 that is precisely what broke the morning: `lucy update`'s autostash
# pop conflicted, left schedule_config.json unmerged, and the 4am batch died on
# it. A watchdog that pulls can be broken by the same pull it is meant to catch,
# so this one runs whatever code is already on disk.
#
# Manual check (posts nothing):
#   bash deploy/orchestrator_heartbeat.sh --dry-run

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/orchestrator-heartbeat-$(date +%Y-%m-%d).log"
echo "[$(date)] heartbeat starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.orchestrator_heartbeat.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] heartbeat finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
