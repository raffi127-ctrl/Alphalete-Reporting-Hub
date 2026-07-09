#!/bin/bash
# Schedule guard — the self-heal for launchd schedule drift, generalized to EVERY
# timed report. Runs daily at 02:45 on the mini via launchd
# (com.alphalete.orchestrator-schedule-guard), BEFORE the earliest daily job (03:00).
#
# WHY: `git pull` updates a deploy/com.alphalete.<x>.plist FILE but never reloads
# launchd, so launchd keeps firing whatever schedule it loaded at boot — the 4am
# orchestrator fired 6am for 15 days, brand-audit-noon once fired 2pm, and every
# timed job carries the same risk. Every diagnostic read the FILE and looked fixed,
# so nobody re-bootstrapped it. schedule_guard.py re-bootstraps EVERY loaded, timed
# com.alphalete.* job from its current plist each night, so launchd can never hold
# a stale schedule and nobody has to remember. install_agent is race-free (bootout
# → confirm gone → bootstrap); no committed plist has RunAtLoad, so a reload never
# fires a job immediately (just refreshes its schedule). At 02:45 nothing has fired
# yet, so every reload is safe. Read the result with `lucy status` or the guard log.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)"
export NO_COLOR=1

# Pull the latest plist FIRST so a schedule edit in the repo lands tonight, THEN
# bootstrap that fresh plist into launchd. Best-effort; only on a clean tree.
if [ -d .git ] && [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
  git pull --ff-only --quiet origin main 2>/dev/null || true
fi

LOG_FILE="$LOG_DIR/orchestrator-schedule-guard-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] schedule guard: re-bootstrapping every timed com.alphalete.* job" > "$LOG_FILE"
"$VENV_PY" -m automations.day_orchestrator.schedule_guard >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] schedule guard finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
