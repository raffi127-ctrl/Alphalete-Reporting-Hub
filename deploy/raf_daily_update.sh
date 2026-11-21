#!/bin/bash
# Raf's Daily Update (office 11280) -> 5:00pm CT Mon-Sat on LUCY 2.
# TEST PHASE (Raf, 2026-10-14): writes "Daily Update 2026 - LUCY" and posts
# the Daily Update thread in #org-indeed-accounts. See the module docstring.
# Standalone because Lucy 2's card scheduler runs observe-only — on 10/14 it
# logged "WOULD run raf_daily_update [dry-run]" and nothing ran.
#
# THEN Omar's (office 24153), same EOD outcome thread, SLACK POST ONLY
# (Megan 2026-10-26) — his sheet is filled by omar_daily_update. Posts in HIS
# channel (offices.py: #omars-mohammad-office-recruiting-24153-rafael-hidalgo,
# Megan 2026-10-26). Raf's stays in #org-indeed-accounts — it does not move.
# THEN Algemar (23965), Cyrus (22815) and Vincent (24290), added 2026-11-19 --
# Slack post only, and their first posts go to MEGAN'S DM rather than an
# owner's room, so she reads one before it reaches anybody.
#
# One after the other, never together: they all drive Lucy 2's one AppStream
# console. Each has its own Hub status and its own failure alert.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.raf_daily_update.run" > /dev/null 2>&1; then
    echo "[$(date)] raf-daily-update SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1

# run_one <report id> <display name> <log prefix> <run.py args...>
run_one() {
    local RID="$1" NAME="$2" PREFIX="$3"; shift 3
    local LOG_FILE="$LOG_DIR/$PREFIX-$(date +%Y-%m-%d-%H%M%S).log"
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('$RID','$NAME')" >> "$LOG_FILE" 2>&1 || true
    "$VENV_PY" -u -m automations.raf_daily_update.run "$@" >> "$LOG_FILE" 2>&1
    local ST=$?
    local PUB=failed
    [ $ST -eq 0 ] && PUB=done
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('$RID','$NAME','$PUB')" >> "$LOG_FILE" 2>&1 || true
    if [ $ST -ne 0 ]; then
        "$VENV_PY" - "$LOG_FILE" "$RID" "$NAME" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    log, rid, name = sys.argv[1:4]
    tail = Path(log).read_text().splitlines()[-15:]
    notify.post_alert(f":rotating_light: *{name}* failed",
                      ["```"] + tail + ["```",
                       f'Re-run: `lucy rerun {rid} --machine "Lucy 2"`'],
                      tag=f"{rid}-failed", cfg=load_config(),
                      incident=f"standalone-{rid}")
except Exception as e:
    print("alert failed:", e)
PY
    fi
    return $ST
}

run_one raf_daily_update "Raf Daily Update" raf-daily-update \
    --write --test-sheet --post --channel C0BH637AM8F
ST_RAF=$?

# SHOWED TO DAY 1 (column K), the one column the daily write cannot fill: a
# row is about an interview day, the column is about that person's start day
# a week later. This comes back for the ones whose start has passed and asks
# the sales board's New Starts block, then the OBCL, who turned up (Megan's
# rule, 2026-10-01). Raf's sheet only -- the other four offices are
# Slack-post-only and have no sheet to fill. Re-runnable and additive: it
# only ever fills an EMPTY cell, so a person neither source has decided yet
# is picked up by a later evening's run.
#
# NOT through run_one, so it publishes NO Hub phase. The Daily Update card
# derives daily_runs from the number of OFFICES and reads "the pill is green
# only when EVERY office posted" -- a sixth phase that is not an office post
# would leave that card permanently unclosable. It still alerts on failure,
# which is the part that matters, and its own log says what it filled.
run_day1() {
    local LOG_FILE="$LOG_DIR/raf-daily-update-day1-$(date +%Y-%m-%d-%H%M%S).log"
    "$VENV_PY" -u -m automations.raf_daily_update.day1 "$@" >> "$LOG_FILE" 2>&1
    local ST=$?
    if [ $ST -ne 0 ]; then
        "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(
        ":rotating_light: *Raf Daily Update · Showed To Day 1* failed",
        ["```"] + tail + ["```",
         # The flags are the point: bare `rerun raf_daily_update_day1` is
         # a DRY run (base_args is empty) and fills nothing (2026-11-21).
         "Re-run: `lucy rerun raf_daily_update_day1 --write --test-sheet`"],
        tag="raf-daily-update-day1-failed", cfg=load_config(),
        incident="standalone-raf_daily_update_day1")
except Exception as e:
    print("alert failed:", e)
PY
    fi
    return $ST
}
run_day1 --write --test-sheet
ST_DAY1=$?

run_one daily_update_omar "Omar Daily Update Post" omar-daily-update-post \
    --office omar --post
ST_OMAR=$?

# THE OTHER THREE 2R OWNERS (Megan, 2026-11-19). The 6pm BOB nudge covers all
# five offices on the `2R Contacts` roster; only Raf and Omar had a Daily
# Update, so the day the other three were nudged about was written up nowhere.
#
# THEIR FIRST POSTS GO TO MEGAN'S DM, not to an owner's room and not to
# #org-indeed-accounts (Megan: "DM me the first posts"). She reads one before
# it reaches anybody. Moving an office to its own room afterwards = set
# `channel` and posts_in_own_channel=True in offices.py and drop --channel
# here. SLACK POST ONLY: no `sheet` in offices.py, so --write would refuse and
# is not passed.
#
# One after another, never together: all of these drive this machine's one
# AppStream console. Each has its own Hub status and its own failure alert.
MEGAN_DM="U04G5HJBGFN"
run_one daily_update_algemar "Algemar Daily Update Post" algemar-daily-update-post \
    --office algemar --post --channel "$MEGAN_DM"
ST_ALGEMAR=$?
run_one daily_update_cyrus "Cyrus Daily Update Post" cyrus-daily-update-post \
    --office cyrus --post --channel "$MEGAN_DM"
ST_CYRUS=$?
run_one daily_update_vincent "Vincent Daily Update Post" vincent-daily-update-post \
    --office vincent --post --channel "$MEGAN_DM"
ST_VINCENT=$?

[ $ST_RAF -eq 0 ] && [ $ST_DAY1 -eq 0 ] && [ $ST_OMAR -eq 0 ] \
    && [ $ST_ALGEMAR -eq 0 ] && [ $ST_CYRUS -eq 0 ] && [ $ST_VINCENT -eq 0 ]
