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

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/focus-report-fixer-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Hub card pills (focus-report-fixer): only a run that writes publishes.
PUBLISH=""
case " $* " in *" --apply "*) PUBLISH=1 ;; esac

echo "[$(date)] focus report fixer starting (args: ${*:-none})" >> "$LOG_FILE"
if [ -n "$PUBLISH" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('focus_report_fixer','Lucy Focus Report Fixer')" >> "$LOG_FILE" 2>&1 || true
fi
"$VENV_PY" -m automations.focus_report_fixer.run "$@" >> "$LOG_FILE" 2>&1
rc=$?   # grab before $(date) resets it
echo "[$(date)] focus report fixer done (exit $rc)" >> "$LOG_FILE"
# Publish either way so a failed run turns the card red instead of grey.
if [ -n "$PUBLISH" ]; then
    if [ "$rc" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('focus_report_fixer','Lucy Focus Report Fixer','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit $rc
