#!/bin/bash
# Digi Docs on Lucy 3 (machine-local; Lucy 3 is Central, and every time on the
# tab is Central too). TWO MODES, because Raf wants each person's documents to
# land 30 minutes before THEIR OWN start time (2026-08-26), not all at once:
#
#   --add        the morning pass. Adds every eligible person on the newest
#                "D2D OBCL <m.d>" tab (every chart on it) to OwnerVille.
#                SENDS THE ONBOARDING EMAIL for the campaign they are added
#                under -- see the warning below. 11:00am.
#
#   --send-tick  the day pass. Fires repeatedly between 06:00 and 16:00 and
#                sends only the people whose start time is within the next 30
#                minutes, so somebody starting at 1:00 gets their bundle at
#                12:30. Reads the Start Time column. Opens no browser at all
#                when nobody is due. NOTHING STARTING AFTER 16:30 IS SENT.
#
# The split is not tidiness: somebody starting at 1pm has to EXIST in
# OwnerVille before their 12:30 send comes round.
#
# ADDING IS NOT FREE (Megan 2026-08-31). Every note in this repo used to say
# this pass "mails nobody". It does: OwnerVille sends the new start their
# ONBOARDING EMAIL the moment they are added, for the campaign they are added
# under. That is how an entire cohort received the Water/Primo welcome instead
# of the AT&T one -- the wrong-campaign bug was not just wrong placement, it
# mailed the wrong email to every one of them. Treat --add with the same care
# as --send-tick: it is a send, and there is no unsend.
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

# THE HOURS GATE COMES FIRST, before anything starts an interpreter.
#
# The send tick fires every 5 minutes so that "30 minutes before" is accurate
# to within five. Gating LATER in the script still works, but the venv probe
# below runs `python -c "import patchright"` up to three times and proc_guard
# starts another — so a gate placed after them spends four interpreter starts
# every five minutes, all day, on the same machine the headshots tick already
# runs on.
#
# It gates on the CLOCK only, not the weekday. It used to also require Monday,
# which was wrong: this report fires on the date written above a chart, and
# those being Mondays is a coincidence of how the sheet is filled in (Megan
# 2026-08-26). Whether today is a chart date needs the sheet, so run.py decides
# that — one cheap read, and it stops before opening a browser.
for _a in "$@"; do
    if [ "$_a" = "--send-tick" ]; then
        # 06:00-15:59 CENTRAL (Lucy 3 is Central, and so is every time on the
        # tab). Was 06:00-20:59 until 2026-08-31.
        #
        # WHY IT ENDS AT 4 (Megan): a person whose start time has PASSED still
        # counts as due, so once the day's cohort is done the tick spent every
        # five minutes until 9pm re-opening all eighteen of their modals just
        # to skip each one as COMPLETED or PENDING. Pointless work, and it held
        # the shared Chrome profile the whole time — which is what kept locking
        # other Lucy 3 jobs out that afternoon.
        #
        # THE COST, stated plainly: a send goes 30 minutes before a start, so
        # nothing starting after 16:30 gets an automated bundle any more. The
        # latest start on 2026-08-31 was 1:30pm, so there is real room — but if
        # a cohort ever starts later than that, raise this hour or those people
        # get nothing and no run says so.
        _HR="$(date +%H)"
        if [ "$_HR" -lt 6 ] || [ "$_HR" -ge 16 ]; then
            exit 0
        fi
        # QUIET DAY BACKOFF. A previous tick already read the sheet and found
        # no chart dated for today. Asking again five minutes later gets the
        # same answer, so skip until that note is 30 minutes old — a quiet day
        # goes from 168 sheet reads to 28. `find -mmin` keeps it in shell, so a
        # skipped tick costs nothing at all.
        _QUIET="output/logs/.digi-docs-quiet-$(date +%Y-%m-%d)"
        if [ -n "$(find "$_QUIET" -mmin -30 2>/dev/null)" ]; then
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
PHASE="--add-only --today"
LIVE="--live"
FWD=()
for _a in "$@"; do
    case "$_a" in
        --add)       PHASE="--add-only --today" ;;
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
# The ADD pass publishes a running row up front: it happens once a day and
# takes minutes, so the yellow pill is worth having. The SEND TICK does not —
# it fires every five minutes and mostly finds nobody due, and a row per firing
# would bury the card under ~168 of them. It publishes AFTER the run instead,
# and only if the run actually did something.
if [ -n "$LIVE" ] && [ "$PHASE" = "--add-only --today" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('digi_docs','Digi Docs')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.digi_docs.run $MODE ${FWD[@]+"${FWD[@]}"} >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Digi Docs finished exit=$ST" >> "$LOG_FILE"

# LAST RESORT ALERT. run.py reports its own failures the moment they happen and
# writes .digi-docs-reported when it does, so this only fires for a run that
# died WITHOUT saying anything — killed at a timeout, OOM, the machine going
# down mid-batch. Those are exactly the failures nothing inside Python can
# catch, and the ones most likely to mean nobody got their documents.
if [ -n "$LIVE" ] && [ "$ST" -ne 0 ] && [ ! -f "$LOG_DIR/.digi-docs-reported" ]; then
    "$VENV_PY" -c "
from automations.digi_docs import slack_post
slack_post.alert_failure('the run was killed before it could report — exit $ST, see $LOG_FILE', dry_run=False)
" >> "$LOG_FILE" 2>&1 || true
fi

# Publish either way so a blocked run is visible on the Hub instead of leaving
# the card grey. [[feedback_launchd_reports_must_publish]]
if [ -n "$LIVE" ] && { [ "$PHASE" = "--add-only --today" ] || [ -f "$LOG_DIR/.digi-docs-did-work" ]; }; then
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('digi_docs','Digi Docs','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

exit 0
