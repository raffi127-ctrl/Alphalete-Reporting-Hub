#!/bin/bash
# Nightly Due Diligence pre-harvest, on the mini via launchd
# (com.alphalete.due-diligence-harvest). Pulls the shared crosstabs (8 weekly
# product + metrics + churn) ONCE into today's cache so any /dd request that day
# is instant (reads the cache instead of an 8-min live pull).
#
# 3:00am CST (Megan): quiet window so it doesn't compete with the 4am flow for
# the Tableau session / Chrome.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/dd-harvest-$(date +%Y-%m-%d).log"
echo "[$(date)] DD harvest starting" > "$LOG_FILE"

# The pull drives Tableau through patchright; a stray human Chrome collides.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# Open a live 'running' pill so the card PULSES while the harvest works; the
# publish_done below closes it green/red — otherwise this 3am job is silent and
# the card stays WHITE even on a clean run (Megan 2026-07-29).
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('due_diligence_harvest','Due Diligence Harvest')" >> "$LOG_FILE" 2>&1 || true
# WEDGE GUARD (2026-11-19). Nothing capped this run, and on 11/19 it hung on a
# Tableau view load from 3:00 until past 7am: the pill never closed, and the
# hung process kept the OwnerVille session lock every other Tableau job on this
# box waits on. A clean harvest takes minutes; 40 min is far past slow and
# still clears before the 4am batch. On a kill the card goes red (exit 124) and
# the harvest's own headless Chrome (the shared Tableau profile) is closed so
# the next run can launch on it.
MAX_RUN_S=2400
"$VENV_PY" -u -m automations.due_diligence.run --harvest --verbose >> "$LOG_FILE" 2>&1 &
_RUN_PID=$!
_waited=0
while kill -0 "$_RUN_PID" 2>/dev/null && [ "$_waited" -lt "$MAX_RUN_S" ]; do
  sleep 5
  _waited=$((_waited + 5))
done
if kill -0 "$_RUN_PID" 2>/dev/null; then
  echo "[$(date)] WEDGE GUARD: harvest still running after ${MAX_RUN_S}s — killing it" >> "$LOG_FILE"
  kill -TERM "$_RUN_PID" 2>/dev/null
  sleep 20
  kill -KILL "$_RUN_PID" 2>/dev/null
  wait "$_RUN_PID" 2>/dev/null
  # The shared profile ONLY -- not .browser_profile_headshots and friends.
  pkill -f 'uploaded/\.browser_profile( |$)' >/dev/null 2>&1 || true
  ST=124
else
  wait "$_RUN_PID"
  ST=$?
fi
echo "[$(date)] DD harvest finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('due_diligence_harvest','Due Diligence Harvest','$_PUB')" >> "$LOG_FILE" 2>&1 || true
exit $ST
