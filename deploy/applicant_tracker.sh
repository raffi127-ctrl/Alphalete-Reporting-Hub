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
"$VENV_PY" -u -m automations.applicant_tracker.run "$PHASE" "${EXTRA_ARGS[@]:-}" >> "$LOG_FILE" 2>&1
echo "[$(date)] applicant/${PHASE} finished exit=$?" >> "$LOG_FILE"
exit 0
