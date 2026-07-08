#!/bin/bash
# Tuesday 10:00am CST — Carlos B2B Captainship Bonus, on Lucy 2 (Carlos's laptop)
# via launchd (com.alphalete.carlos-captainship-bonus-tue).
#
# Inserts a fresh leftmost week column on the "Carlos B2B Captainship" tab of the
# *All In One - CARLOS* sheet, fills each active rep's Total Activations for
# Carlos' B2B team + the four metric cells (team 0-30 churn %, personal 0-30
# churn %, 31-60 activation %, non-payment %) pulled live from Tableau
# (ATTTRACKER-B2B / Captain Team), lets Money Made / TOTAL AMOUNT recompute,
# re-points the chart, and saves the PDF to Downloads. Idempotent: if this
# week's column already exists it refreshes in place (--force-insert overrides).
#
# Runs off THIS machine's warm Tableau session (patchright), same path the mini's
# Tableau reports use. Lucy 2 must have a seeded + holder-warmed Tableau session —
# one-time seed: python -m automations.shared.tableau_patchright --login.
#
# Tuesday (not Monday like the headcount job) so the just-ended week's churn %s
# have settled before we read them; the module defaults to _current_we_sunday
# (last completed week), so Tuesday's run fills the prior Sunday's column.
#
# Manual test without writing:  bash deploy/carlos_captainship_bonus_tue.sh --dry-run
# (--dry-run passes through to the module — pulls + shows the plan, writes nothing.)
#
# CADENCE: the plist fires once, Tuesday 10:00am, machine LOCAL time (Lucy 2 is
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

LOG_FILE="$LOG_DIR/carlos-captainship-bonus-tue-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Carlos B2B Captainship Bonus weekly run starting (extra args: ${*:-none})" > "$LOG_FILE"

# LIVE by default (fills the sheet). Any extra arg (e.g. --dry-run) is appended.
"$VENV_PY" -u -m automations.carlos_captainship_bonus.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Carlos B2B Captainship Bonus run finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Carlos B2B Captainship Bonus failed (exit $ST) — check the log; the Tableau login may have expired or a roster row didn't match\" with title \"Captainship Bonus\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
