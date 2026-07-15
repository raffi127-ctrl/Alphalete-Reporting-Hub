#!/bin/bash
# Weekdays 9:30am — Car-Rides Cleanup, on Lucy 2, via launchd
# (com.alphalete.car-rides-cleanup).
#
# Reconciles each car-ride leader's OwnerVille/TeleMapper territory against the
# Stations tab of the Vantura Master Sales Board, both campaigns (B2B AT&T SBS +
# B2B-BOX-Energy). Fully unattended: board via gspread, OwnerVille via the
# exported session the session-holder keeps warm — if that session is stale the
# run FLAGS it and stops (it never drives the login form / Cloudflare check).
#
# SAFETY: DRY-RUN by default (this wrapper passes NO mode flag; the module
# defaults to --dry-run — it plans + reports, changes nothing in OwnerVille).
# Flip to live only after dry-run plans are log-verified, by appending --live.
#
# Manual test:   bash deploy/car_rides_cleanup.sh            # dry-run
#                bash deploy/car_rides_cleanup.sh --probe    # DOM evidence dump
#
# CADENCE: plist fires weekdays 9:30am machine LOCAL time. TIME KNOB: edit
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

LOG_FILE="$LOG_DIR/car-rides-cleanup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] car-rides cleanup starting (extra args: ${*:-none})" > "$LOG_FILE"

# DRY-RUN by default (no mode flag). Append --live here only after the dry-run
# plan is log-verified on Lucy 2. Extra args pass straight through.
"$VENV_PY" -u -m automations.car_rides.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] car-rides cleanup finished exit=$ST" >> "$LOG_FILE"
exit 0
