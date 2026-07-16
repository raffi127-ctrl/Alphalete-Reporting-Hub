#!/bin/bash
# Monday 7:00am CST — Carlos Captainship Headcount, on Lucy 2 (Carlos's laptop)
# via launchd (com.alphalete.carlos-captainship-headcount-mon).
#
# Inserts a fresh leftmost week column on the "Captainship Head count" tab of the
# *All In One - CARLOS* sheet, fills each active owner's Rep Count (pulled live
# from Tableau ATTTRACKER-B2B / D2D1-PAGERV3, the "B2B One Pager V3"), recomputes
# the Total (SUM formula) and sorts active owners high->low. Idempotent: if this
# week's column already exists it refreshes in place (--force-insert overrides).
#
# Runs off THIS machine's warm Tableau session (patchright), same path the mini's
# Tableau reports use. Lucy 2 must have a seeded + holder-warmed Tableau session —
# one-time seed: python -m automations.shared.tableau_patchright --login.
#
# 7:00am CST is before the Fiber/NDS/B2B "This Week" filter rolls to the new week
# (the module defaults to _current_we_sunday = last completed week, so Monday's
# run fills yesterday's Sunday column).
#
# Manual test without writing:  bash deploy/carlos_captainship_headcount_mon.sh --dry-run
# (--dry-run passes through to the module — pulls + shows the plan, writes nothing.)
#
# CADENCE: the plist fires once, Monday 7:00am, machine LOCAL time (Lucy 2 is
# Central). TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
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

LOG_FILE="$LOG_DIR/carlos-captainship-headcount-mon-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Carlos Captainship Headcount weekly run starting (extra args: ${*:-none})" > "$LOG_FILE"

# LIVE by default (fills the sheet). Any extra arg (e.g. --dry-run) is appended.
"$VENV_PY" -u -m automations.carlos_captainship_headcount.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Carlos Captainship Headcount run finished exit=$ST" >> "$LOG_FILE"

# Report this standalone run to the Hub so the card's pill reflects a REAL
# success/failure (Megan 2026-07-14: the card stayed grey even on a clean run, so
# success looked identical to a silent miss). Skip on --dry-run. Best-effort.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('carlos_captainship_headcount','Carlos Captainship Headcount','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Carlos Captainship Headcount failed (exit $ST) — check the log; the Tableau login may have expired or a roster row didn't match\" with title \"Captainship Headcount\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
