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
"$VENV_PY" -u -m automations.due_diligence.run --harvest --verbose >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] DD harvest finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('due_diligence_harvest','Due Diligence Harvest','$_PUB')" >> "$LOG_FILE" 2>&1 || true
exit $ST
