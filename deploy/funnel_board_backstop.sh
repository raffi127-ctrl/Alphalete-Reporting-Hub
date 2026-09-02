#!/bin/bash
# Recruiting Funnel Board — BACKSTOP. The retry the 1am chain does not have.
#
# WHY (Eve 2026-09-02). funnel_board is step 1 of com.alphalete.recruiting-chain-1am
# and NOTHING ELSE RUNS IT: schedule_config gives it cadence.weekdays [] so the 4am
# orchestrator skips it by design (Carlos 2026-08-29 — one AppStream login at a
# time), and com.alphalete.funnel-board-hourly is not loaded on Lucy 2 (disabled
# 2026-08-31). Steps 2 and 3 of the chain get a second chance from the 1pm refresh;
# step 1 does not. So on BOTH 9/1 and 9/2, when the chain was killed inside
# funnel_board's AppStream login, the Board and Trend tabs sat on the previous day's
# numbers until a person read the 10 AM alert and ran `lucy rerun funnel_board` by
# hand. That hand-run is what this file replaces.
#
# THIS IS NOT ANOTHER CADENCE. It re-runs only when the day has no clean pass yet;
# on a normal morning it reads a couple of log files and exits. That distinction
# matters: the hourly agent was retired precisely because a second timer fought the
# chain for the AppStream session.
#
# Usage:  bash deploy/funnel_board_backstop.sh [--force] [--dry-run]
#           --force    run even if today already looks clean (for testing)
#           --dry-run  pass --dry-run to the report (writes nothing) and publish
#                      nothing — a rehearsal must not paint a colour on the Hub
set -u
cd "$(dirname "$0")/.." || exit 1

TODAY=$(date +%Y-%m-%d)
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/funnel-board-backstop-$TODAY-$(date +%H%M%S).log"

# Same interpreter ladder as funnel_board_hourly.sh — this drives the same module.
VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

FORCE=0
DRY=0
for a in "$@"; do
    case "$a" in
        --force)   FORCE=1 ;;
        --dry-run) DRY=1 ;;
    esac
done

say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

_publish() {  # _publish <success|failed>
    [ "$DRY" -eq 0 ] || return 0
    "$VENV_PY" -c "import sys
from automations.day_orchestrator import hub_publish
hub_publish.publish_done('funnel_board', 'Recruiting Funnel Board', sys.argv[1])" \
        "$1" >> "$LOG" 2>&1 || true
}

say "funnel-board backstop starting (force=$FORCE dry=$DRY)"

# ---------------------------------------------------------------- 1. is it alive?
# Never fight a pass that is already going: run.py's state/run.lock would make the
# second one a silent no-op anyway, and two writers clobbered a manager's whole
# column once already (Jacob Dover, 2026-08-10).
if pgrep -f "automations.funnel_board.run" > /dev/null 2>&1; then
    say "SKIPPED — a funnel_board run is alive right now"
    exit 0
fi
if pgrep -f "deploy/recruiting_chain.sh" > /dev/null 2>&1; then
    say "SKIPPED — the recruiting chain is still running"
    exit 0
fi

# ------------------------------------------------------- 2. did it deliver today?
# The bar is `build exited 0`, which means build.py wrote the Sheet. An overall
# exit 1 ON TOP of that is the PARTIAL case (one office's AppStream pull failed and
# those managers kept their old numbers) — a partial is not a lost day, and a retry
# would only walk into the same office denial, so it does not earn a re-run.
#
# Covers all three name shapes a pass can leave: funnel-board-hourly-<date>-*.log
# (the chain's step 1), rerun-<date>-*-funnel_board.log (`lucy rerun`), and this
# script's own funnel-board-backstop-<date>-*.log.
CLEAN=""
for f in "$LOG_DIR"/*funnel*"$TODAY"*.log "$LOG_DIR"/*"$TODAY"*funnel*.log; do
    [ -f "$f" ] || continue
    if grep -q "build exited 0" "$f" 2>/dev/null; then CLEAN="$f"; break; fi
done

if [ -n "$CLEAN" ] && [ "$FORCE" -eq 0 ]; then
    say "nothing to do — today already has a clean pass ($(basename "$CLEAN"))"
    # Say so on the Hub. The chain's step 1 publishes NOTHING under this report id
    # (funnel_board_hourly.sh deliberately never published, and the chain publishes
    # only its own 'recruiting_chain' card), so since the 2026-08-29 move the card
    # has had no run on a GOOD day either — which is the same white "no run logged"
    # a genuinely dead report shows. This is not a colour for work we did not do:
    # we just verified a real clean pass, today, in the log it wrote.
    _publish success
    exit 0
fi
[ "$FORCE" -eq 1 ] && say "--force: running even though today looks clean"

# ------------------------------------------------------------- 3. free the browser
# The 2026-09-02 root cause: the chain walked into a locked Chrome profile at 1 AM
# and the login never came up. Both paths that DO work do this first — the
# orchestrator (run.py) and `lucy rerun` (mini_control). --close removes a HUMAN's
# Chrome; --unstick removes OUR OWN orphan (PPID 1) still holding the shared
# profile's ProcessSingleton. The CLI's --unstick only knows the shared profile, so
# free funnel_board's OWN profile too — that is the one its login actually opens.
say "freeing chrome profiles"
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close --unstick \
    >> "$LOG" 2>&1 || true
"$VENV_PY" -u -c "from automations.day_orchestrator import chrome_guard as g
print('funnel profile freed:', g.unstick_profile('.appstream_profile_funnel', verbose=False))" \
    >> "$LOG" 2>&1 || true

# ------------------------------------------------------------------- 4. run it
# Through the same wrapper the chain uses, so there is exactly one definition of
# how this report starts (env vars, headed Chrome, its own pgrep guard, its log).
say "no clean pass today — re-running funnel_board"
if [ "$DRY" -eq 1 ]; then
    bash deploy/funnel_board_hourly.sh --dry-run >> "$LOG" 2>&1 &
else
    bash deploy/funnel_board_hourly.sh >> "$LOG" 2>&1 &
fi
STEP_PID=$!

# WATCHDOG. A normal pass is ~3 min. The failure this backstop exists for HANGS —
# it sits on an AppStream login nobody can clear — and a hang here would hold the
# run lock through the morning and wedge every later pass, which is worse than the
# missed run. 30 min, then kill the module (the wrapper only forwards its exit).
TIMEOUT_S=1800
(
    sleep "$TIMEOUT_S"
    if kill -0 "$STEP_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] TIMEOUT after ${TIMEOUT_S}s — killing the run" >> "$LOG"
        pkill -f "automations.funnel_board.run" 2>/dev/null
        kill -9 "$STEP_PID" 2>/dev/null
    fi
) &
WATCHDOG_PID=$!

wait "$STEP_PID"
RC=$?
kill "$WATCHDOG_PID" 2>/dev/null

# A killed run never fires run.py's atexit, so the lock outlives it and blocks the
# next pass for STALE_MIN (90 min) while those passes exit 0 — the report looks
# healthy and does nothing. Same clean-up `lucy rerun funnel_board_unlock` does,
# and like it, only when nothing is actually running.
if [ "$RC" -ne 0 ] && ! pgrep -f "automations.funnel_board.run" > /dev/null 2>&1; then
    rm -rf automations/funnel_board/state/run.lock 2>/dev/null && \
        say "cleared the run lock left behind by the failed pass"
fi

if [ "$RC" -eq 0 ]; then
    say "backstop pass finished clean"
    _publish success
else
    say "backstop pass FAILED (exit $RC) — see $LOG and the funnel-board-hourly log"
    _publish failed
fi
exit "$RC"
