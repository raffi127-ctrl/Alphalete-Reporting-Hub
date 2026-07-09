#!/bin/bash
# Orchestrator schedule guard — the self-heal for the recurring 4am→6am launchd
# drift (2026-07-07 / -08 / -09). Runs daily at 03:40 on the mini via launchd
# (com.alphalete.orchestrator-schedule-guard), 20 min BEFORE the 4am orchestrator.
#
# WHY: `git pull` updates deploy/com.alphalete.day-orchestrator.plist (the FILE)
# but never reloads launchd, so launchd keeps firing whatever schedule it loaded
# at boot — the plist said Hour 4 for 15 days while launchd kept firing Hour 6.
# Every diagnostic read the FILE and looked fixed, so nobody re-bootstrapped it.
# This guard re-bootstraps the day-orchestrator from the current (Hour 4) plist
# EVERY night, so launchd can never hold a stale in-memory schedule. install_agent
# is race-free (bootout → confirm gone → bootstrap) and idempotent; at 03:40 the
# orchestrator isn't running yet, so the bootout is safe (and clears a rare
# hung-past-midnight batch as a bonus). Read the result with `lucy status` or the
# guard log below.

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
echo "[$(date)] schedule guard: re-bootstrapping com.alphalete.day-orchestrator" > "$LOG_FILE"
"$VENV_PY" -m automations.day_orchestrator.install_agent day-orchestrator >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] schedule guard finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
