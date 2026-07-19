#!/bin/bash
# Mon-Sat, 9 morning passes (8:30, 9:00, 9:30, 10:00, 10:30, 10:40, 10:50,
# 11:00, 11:15) — Car-Rides Cleanup, on Lucy 2, via launchd
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
# CADENCE: plist fires Mon-Sat at the 9 morning times above, machine LOCAL
# time. TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: passes come as close as 10 min apart; if the previous pass is
# still going, SKIP this tick instead of fighting it over the browser profile.
if pgrep -f "automations.car_rides.run" > /dev/null 2>&1; then
    echo "[$(date)] car-rides cleanup SKIPPED — previous pass still running"
    exit 0
fi

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

# LIVE on the schedule (Carlos 2026-07-18: the cleanup should be applying, not
# just planning). --live is added ONLY when no mode flag was passed, because
# --live/--dry-run/--probe are mutually exclusive in the CLI — so a manual
#   bash deploy/car_rides_cleanup.sh --dry-run
# still previews without editing, and --probe still works.
MODE="--live"
for a in "$@"; do
  case "$a" in --live|--dry-run|--probe) MODE=""; break;; esac
done
"$VENV_PY" -u -m automations.car_rides.run $MODE "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] car-rides cleanup finished exit=$ST" >> "$LOG_FILE"

# Report each pass to the Hub so the card pill reflects real progress through
# the morning (1/9 -> 9/9). Skipped ticks exit before this, so they never count.
# EXIT CODES: 0 = clean, 3 = ran fine but raised FLAGS for Carlos (stale
# territory / ambiguous name) — both mean the pass RAN, so both publish
# 'success'. Anything else (e.g. 4 = Stations read failed) is a real failure.
# Best-effort: never fail the run over reporting.
case " $* " in
  *" --probe "*) : ;;
  *)
    if [ "$ST" -eq 0 ] || [ "$ST" -eq 3 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('car_rides','Car-Rides Cleanup (OwnerVille territories)','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac
exit 0
