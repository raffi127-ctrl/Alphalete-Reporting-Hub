#!/bin/bash
# Applicant Tracker sync (Francia, consolidated) — RUNS ON LUCY 1.
#
# One module (automations.applicant_tracker.run) with two phases that share ONE
# ApplicantStream login:
#   morning  reads YESTERDAY  (Call List + 2R Status)  — normally the 4am
#            orchestrator runs this; this wrapper can too for a manual pass.
#   evening  reads TODAY      (2R Retention + First-Day) — the 8pm launchd
#            agent com.alphalete.applicant-evening calls `... evening`.
#
# Usage:  bash deploy/applicant_tracker.sh {morning|evening} [--dry-run]
set -u
cd "$(dirname "$0")/.." || exit 1

PHASE="${1:-}"
shift || true
EXTRA_ARGS=("$@")   # e.g. --dry-run

case "$PHASE" in
    morning|evening) : ;;
    *) echo "usage: applicant_tracker.sh {morning|evening} [--dry-run]" >&2; exit 2 ;;
esac

# The mini runs 3.9; the laptop 3.14. Prefer the pinned interpreter when present,
# else whatever the venv provides — never hardcode one (cross-platform rule).
VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export HEADLESS=1                      # scheduled runs are invisible
export PYTHONPATH="$(pwd)"

if pgrep -f "automations.applicant_tracker.run ${PHASE}" > /dev/null 2>&1; then
    echo "[$(date)] applicant/${PHASE} SKIPPED — a previous pass is still running"
    exit 0
fi

LOG_FILE="$LOG_DIR/applicant-${PHASE}-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] applicant/${PHASE} starting (args: ${EXTRA_ARGS[*]:-})" > "$LOG_FILE"
# Build argv explicitly. Do NOT inline "${EXTRA_ARGS[@]:-}": under `set -u`, an
# EMPTY array expands to a single stray "" arg, which argparse rejects as an
# unrecognized positional (exit 2) — that silently killed EVERY scheduled run
# (no extra args), so run.py never started and neither 2R Retention nor
# First-Day ever wrote. Forward EXTRA_ARGS only when there actually are some.
CMD=("$VENV_PY" -u -m automations.applicant_tracker.run "$PHASE")
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi
# Open a live 'running' pill so the card PULSES while the phase works; the
# publish_done below closes it green/red. Skip on --dry-run. (Megan 2026-07-29)
case " ${EXTRA_ARGS[*]:-} " in
  *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('applicant_sync','Applicant Tracker Sync')" >> "$LOG_FILE" 2>&1 || true ;;
esac
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] applicant/${PHASE} finished exit=$ST" >> "$LOG_FILE"
# Publish real status so a FAILED evening run isn't silent — this wrapper used to
# `exit 0`, hiding crashes from launchd AND writing no Hub row, so nothing ever
# alerted #claudecorrections. Now a fail reds the card + the 10-min digest posts
# it. Skip on --dry-run. (Megan 2026-07-29)
case " ${EXTRA_ARGS[*]:-} " in
  *" --dry-run "*) : ;;
  *) if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
     "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('applicant_sync','Applicant Tracker Sync','$_PUB')" >> "$LOG_FILE" 2>&1 || true ;;
esac
exit $ST
