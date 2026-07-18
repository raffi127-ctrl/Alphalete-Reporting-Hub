#!/bin/bash
# Daily 7:00am (machine-local; Lucy 2 is Central) — Vantura Master Sales Board
# churn + activations refresh, on Lucy 2, via launchd
# (com.alphalete.vantura-churn-daily).
#
# Runs automations.vantura_churn.run: pull each owner's 60-day Order Log + the
# Churn Rates dashboard from Tableau (Lucy 2's warm session), compute the 0-30
# bases/disconnects, RECONCILE against the dashboard's 0-30 cell, and only then
# write the live board (Carlos: Churn + Activations; Atef: Churn - Atef). On a
# reconcile mismatch the run writes NOTHING and fails loudly — that gate is the
# whole safety story, so no extra mode flag is needed here (live is the module
# default; --dry-run is the opt-in).
#
# Manual test:   bash deploy/vantura_churn_daily.sh --dry-run
#
# CADENCE: the plist fires daily 7:00am machine-local. TIME KNOB: edit
# StartCalendarInterval in the plist, not this wrapper.
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

# Skip if a previous pass (or a manual queue run) is still going — the poller
# and launchd share one Chrome profile per module; two vantura_churn runs
# would fight over it.
if pgrep -f "automations.vantura_churn.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura_churn already running — skipping this fire" \
        >> "$LOG_DIR/vantura-churn-daily.skip.log"
    exit 0
fi

LOG_FILE="$LOG_DIR/vantura-churn-daily-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Vantura churn+activations refresh starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.vantura_churn.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Vantura churn+activations refresh finished exit=$ST" >> "$LOG_FILE"
exit 0
