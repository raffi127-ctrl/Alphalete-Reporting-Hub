#!/bin/bash
# Daily 7:45am CST — Texas de Brazil monthly competition standings, on Lucy 1
# (the mini) via launchd (com.alphalete.texas-de-brazil-745).
#
# Builds the flyer + standings PDF (month is AUTO-derived from the current date)
# and, with --send, posts it AS Lucy to #alphalete-sales + #alphalete-lvl1-chat
# and iMessages the "Alphalete A-Team Chat" group on this machine.
#
# The report itself lives in the shared Report Library (Google Sheet), not the
# repo, so we (1) materialize the latest library code into the local cache, then
# (2) run it. 7:45am is OUTSIDE the 4am chrome_guard window, so we close any
# stray human Chrome here before the headless PDF render.
#
# Manual DRY test (build PDF, print delivery plan, NO posts):
#   bash deploy/texas_de_brazil_745.sh --dry-run
# Manual LIVE post:
#   bash deploy/texas_de_brazil_745.sh            (defaults to --send)
#
# CADENCE: the plist fires once daily, 7:45am, machine LOCAL time (the mini is
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

MODULE="automations.uploaded._shared.june_texas_de_brazil_monthly_competition"
LOG_FILE="$LOG_DIR/texas-de-brazil-745-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Texas de Brazil daily run starting (extra args: ${*:-none})" > "$LOG_FILE"

# Close a human's stray Chrome so the headless PDF render doesn't collide.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# Materialize the latest script text from the Report Library Sheet into the local
# cache, so a Sheet edit propagates to the scheduled run without a code deploy.
"$VENV_PY" -u -c "from automations import dashboard as D; D._read_shared_library_rows()" >> "$LOG_FILE" 2>&1 || true

# Bridge the Hub-card dinner date across machines: merge the git-synced seed
# (deploy/texas_de_brazil_manual_inputs.json) into this machine's local manual-
# inputs JSON so the flyer shows the real date instead of "TO BE DETERMINED".
# Only touches dinner_schedule — leaders are left untouched.
"$VENV_PY" -u -m automations.day_orchestrator.tdb_sync_inputs >> "$LOG_FILE" 2>&1 || true

# LIVE by default (--send). Any extra arg (e.g. --dry-run) is appended and wins.
if [ "$#" -eq 0 ]; then set -- --send; fi
"$VENV_PY" -u -m "$MODULE" "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Texas de Brazil run finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Texas de Brazil daily post failed (exit $ST) — check the log; Chrome/OAuth/Slack or the iMessage group may need attention\" with title \"Texas de Brazil\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
