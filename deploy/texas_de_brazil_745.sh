#!/bin/bash
# Daily 7:45am CST — Texas de Brazil monthly competition standings, on Lucy 1
# (the mini) via launchd (com.alphalete.texas-de-brazil-745).
#
# Builds the flyer + standings PDF (month is AUTO-derived from the current date)
# and, with --send, posts it AS Lucy to #alphalete-sales + #alphalete-lvl1-chat.
#
# iMessage DELIVERY DISABLED 2026-07-22: Apple disabled iMessage on the mini's
# account, so the group text stopped arriving (osascript still reported "sent",
# into a dead/stale thread). We turn it off cleanly via the module's OWN built-in
# skip — export an EMPTY TDB_IMESSAGE_CHAT_ID below, and send_imessage() returns
# "SKIPPED — no group chat id configured". Slack posting is unaffected. To turn it
# back on: set TDB_IMESSAGE_CHAT_ID to the CURRENT A-Team group chat GUID (the old
# hardcoded chat72256665735645227 is stale) and re-enable.
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

# Disable the iMessage step (Apple disabled iMessage on this account, 2026-07-22).
# EMPTY overrides the module's default chat id, so send_imessage() skips cleanly;
# Slack posting is untouched. Set to the live A-Team GUID to re-enable later.
export TDB_IMESSAGE_CHAT_ID=""

MODULE="automations.uploaded._shared.june_texas_de_brazil_monthly_competition"
LOG_FILE="$LOG_DIR/texas-de-brazil-745-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Texas de Brazil daily run starting (extra args: ${*:-none})" > "$LOG_FILE"

# Close a human's stray Chrome so the headless PDF render doesn't collide.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# Materialize the latest script text from the Report Library Sheet into the local
# cache, so a Sheet edit propagates to the scheduled run without a code deploy.
"$VENV_PY" -u -c "from automations import dashboard as D; D._read_shared_library_rows()" >> "$LOG_FILE" 2>&1 || true

# Generic self-heal: if the cell was wiped/broken (lost the send layer or won't
# compile), restore the last-known-good backup before running, so it still sends.
"$VENV_PY" -u -m automations.day_orchestrator.library_self_heal june_texas_de_brazil_monthly_competition >> "$LOG_FILE" 2>&1 || true

# Sync the Hub-card dinner date + backfill leaders from the shared 'TdB Manual
# Inputs' store into this machine's local JSON (dinner_schedule + leaders text).
"$VENV_PY" -u -m automations.day_orchestrator.tdb_sync_inputs >> "$LOG_FILE" 2>&1 || true

# LIVE by default (--send). Any extra arg (e.g. --dry-run) is appended and wins.
if [ "$#" -eq 0 ]; then set -- --send; fi
"$VENV_PY" -u -m "$MODULE" "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Texas de Brazil run finished exit=$ST" >> "$LOG_FILE"

# Mark the Hub card GREEN on a successful LIVE run (skip dry-runs). Mirrors what
# run_library_report does for the `lucy rerun --send` path.
if [ "$ST" -eq 0 ] && [[ " $* " != *" --dry-run "* ]]; then
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish as H; H.publish_done('june_texas_de_brazil_monthly_competition','Texas De Brazil Monthly Competition')" >> "$LOG_FILE" 2>&1 || true
fi

if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Texas de Brazil daily post failed (exit $ST) — check the log; Chrome/OAuth/Slack or the iMessage group may need attention\" with title \"Texas de Brazil\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
