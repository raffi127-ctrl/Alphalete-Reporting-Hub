#!/bin/bash
# Lucy Focus Report Fixer — the four Focus Report books (ATT Program,
# Alphalete Org 1on1s, NDS Program, Carlos 1on1s): backs up and fixes #REF!
# formulas, holes in formula rows and dead color rules; report in
# output/focus_report_fixer. Mondays 18:00 on LUCY 4 via launchd
# (com.alphalete.focus-report-fixer) -- Eve 2026-10-19: "con que se chequeen
# los lunes al final del día está bien". See automations/focus_report_fixer/.
#
#   bash deploy/focus_report_fixer.sh                       # audit only, writes nothing
#   bash deploy/focus_report_fixer.sh --all-tabs --apply    # what the agent runs

set -u
cd "$(dirname "$0")/.." || exit 1

# Weekly agent: pull first so a fix pushed during the week runs on Monday
# (the auto-pull is per wrapper, not per machine).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/focus-report-fixer-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# No Hub publish here: run.py colours its step on the four Focus Report
# cards itself (hub_phase); it has no card of its own.

echo "[$(date)] focus report fixer starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.focus_report_fixer.run "$@" >> "$LOG_FILE" 2>&1
rc=$?   # grab before $(date) resets it
echo "[$(date)] focus report fixer done (exit $rc)" >> "$LOG_FILE"
exit $rc
