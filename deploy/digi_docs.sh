#!/bin/bash
# Digi Docs on Lucy 3 (machine-local; Lucy 3 is Central, and every time on the
# tab is Central too). TWO MODES, because Raf wants each person's documents to
# land 30 minutes before THEIR OWN start time (2026-08-26), not all at once:
#
#   --add        the morning pass. Adds every eligible person on the newest
#                "D2D OBCL <m.d>" tab (every chart on it) to OwnerVille.
#                MAILS NOBODY. Monday 8:00am, in the quiet 8-10 window.
#
#   --send-tick  the day pass. Fires repeatedly and sends only the people whose
#                start time is within the next 30 minutes, so somebody starting
#                at 1:00 gets their bundle at 12:30. Reads the Start Time
#                column. Opens no browser at all when nobody is due.
#
# The split is not tidiness. Adding early is free because it mails nobody, and
# adding late is not: somebody starting at 1pm has to EXIST in OwnerVille
# before their 12:30 send comes round.
#
# Generating the bundle IS the send — OwnerVille mails the nine documents
# itself. There is no separate send step and no unsend.
#
# SENDING IS IRREVERSIBLE — generating a bundle mails a nine-document contract
# packet and there is no unsend. The module defaults to dry-run; this WRAPPER
# is what passes --live. To preview what a fire would do:
#
#   bash deploy/digi_docs_monday.sh --send-tick --dry-run
#
# CADENCE: two plists, com.alphalete.digi-docs-add (Monday 08:00) and
# com.alphalete.digi-docs-send (Monday, through the day). TIME KNOBS live in
# those, not here. The 30-minute lead is config.SEND_LEAD_MINUTES.
set -u
cd "$(dirname "$0")/.." || exit 1

# THE DAY GATE COMES FIRST, before anything starts an interpreter.
#
# The send tick fires every 5 minutes so that "30 minutes before" is accurate
# to within five, and it only means anything on start day in office hours.
# Gating LATER in the script still works, but the venv probe below runs
# `python -c "import patchright"` up to three times and proc_guard starts
# another — so a gate placed after them spends four interpreter starts every
# five minutes, all week, on the same machine the headshots tick already runs
# on. Roughly two thousand of those a week to discover it is Tuesday.
#
# `date +%u`: 1 = Monday. Pure shell, no Python, no Sheet read.
for _a in "$@"; do
    if [ "$_a" = "--send-tick" ]; then
        _DOW="$(date +%u)"
        _HR="$(date +%H)"
        if [ "$_DOW" != "1" ] || [ "$_HR" -lt 6 ] || [ "$_HR" -gt 20 ]; then
            exit 0
        fi
    fi
done
mkdir -p output/logs
LOG_DIR="output/logs"

# Probe for an interpreter that can actually drive a browser rather than
# guessing a version: this repo's venv holds several and patchright is not
# installed for all of them on every machine.
VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import patchright" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with patchright — cannot drive OwnerVille" \
        >> "$LOG_DIR/digi-docs.skip.log"
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Two concurrent runs would walk the same people through the same click-path.
# proc_guard, not a raw pgrep: the fleet's old `pgrep -f "-m automations.x"`
# guards were silently dead on macOS for months (2026-08-24) because BSD pgrep
# read the leading -m as an option and answered "" to a question it never got
# to ask. [[reference_pgrep_guard_dead]]
BUSY="$("$VENV_PY" -c "from automations.day_orchestrator import proc_guard; print(','.join(proc_guard.running_pids('automations.digi_docs.run')))" 2>/dev/null)"
if [ -n "$BUSY" ]; then
    echo "[$(date)] digi_docs already running (pid $BUSY) — skipping this fire" \
        >> "$LOG_DIR/digi-docs.skip.log"
    exit 0
fi

# Mode comes from the plist. --dry-run anywhere wins and is NOT forwarded
# (run.py has no such flag — dry is simply the absence of --live).
PHASE="--add-only"
LIVE="--live"
FWD=()
for _a in "$@"; do
    case "$_a" in
        --add)       PHASE="--add-only" ;;
        --send-tick) PHASE="--send-only --due-now" ;;
        --dry-run)   LIVE="" ;;
        *)           FWD+=("$_a") ;;
    esac
done
MODE="$PHASE $LIVE"


LOG_FILE="$LOG_DIR/digi-docs-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Digi Docs starting (mode: $MODE, extra args: ${FWD[*]:-none})" > "$LOG_FILE"

# ONE Hub card, two passes (Megan 2026-08-26): both the add pass and the send
# pass publish under the SAME report id, so the card's daily_runs:2 pill shows
# 1/2 after the morning add and greens once the day's sends are done. A second
# report id here would auto-register a phantom library card.
if [ -n "$LIVE" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('digi_docs','Digi Docs')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.digi_docs.run $MODE ${FWD[@]+"${FWD[@]}"} >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Digi Docs finished exit=$ST" >> "$LOG_FILE"

# Publish either way so a blocked run is visible on the Hub instead of leaving
# the card grey. [[feedback_launchd_reports_must_publish]]
if [ -n "$LIVE" ]; then
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('digi_docs','Digi Docs','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

exit 0
