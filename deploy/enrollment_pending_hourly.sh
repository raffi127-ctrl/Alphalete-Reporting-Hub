#!/bin/bash
# Pending enrollments check — HOURLY 9am–10pm. RUNS ON LUCY 1.
#
# Megan 2026-08-19: moved off the 4am orchestrator pass and onto its own hourly
# cadence. It is a safety net, not a report — it posts to the corrections channel
# only when an office enrollment is sitting in the 'Office Onboarding' sheet
# un-applied. Once a day at 4am meant an enrollment added at 9:05am waited a full
# day to be noticed; hourly through the working day closes that gap.
#
# Safe to run 14x a day: pending_alert READS the sheet and posts only on a real
# pending row. Nothing is written, so a repeated pass is a no-op, and the module
# owns its own de-dupe so the channel does not get the same nag every hour.
#
# Usage:  bash deploy/enrollment_pending_hourly.sh [args]
set -u
cd "$(dirname "$0")/.." || exit 1

EXTRA_ARGS=("$@")

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
export PYTHONPATH="$(pwd)"

# Skip instantly if a pass is still alive — including the orchestrator's, which
# runs the same module path (same guard funnel_board_hourly uses).
if pgrep -f "automations.office_onboarding.pending_alert" > /dev/null 2>&1; then
    echo "[$(date)] enrollment_pending SKIPPED — a previous pass is still running"
    exit 0
fi

LOG_FILE="$LOG_DIR/enrollment-pending-$(date +%Y-%m-%d).log"
echo "[$(date)] enrollment_pending starting" >> "$LOG_FILE"

# Build argv explicitly. Under `set -u` an EMPTY array inlined as
# "${EXTRA_ARGS[@]:-}" expands to one stray "" arg that argparse rejects — the
# trap that silently killed every scheduled applicant_tracker run once.
CMD=("$VENV_PY" -u -m automations.office_onboarding.pending_alert)
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] enrollment_pending finished exit=$ST" >> "$LOG_FILE"

# Deliberately NOT publishing a Hub card per pass — 14 rows a day would bury the
# once-daily reports. The card is lit by the pass that actually finds something,
# and by the standing LaunchAgent-publishes rule via the module itself.
exit $ST
