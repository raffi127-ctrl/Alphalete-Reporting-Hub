#!/bin/bash
# Recruiting chain — run the dashboard's AppStream reports back-to-back, in
# dependency order, instead of on independent timers (Carlos 2026-08-29).
#
# WHY A CHAIN. funnel_board, indeed_source_report and ad_sales_board all log
# into AppStream and all write the Alphalete Recruiting Dashboard. On separate
# timers they overlapped, fought for the AppStream session, and (with the
# resume pusher also logging in) tripped Cloudflare. Running them in sequence
# means each starts when the previous one has actually FINISHED — no guessing
# at durations, and only one AppStream login at a time.
#
#   1am chain:  funnel_board -> indeed_source_report -> ad_sales_board
#   1pm chain:  indeed_source_report -> ad_sales_board
#
# Usage:  bash deploy/recruiting_chain.sh full       # all three (1am)
#         bash deploy/recruiting_chain.sh refresh    # indeed + ad sales (1pm)
#         bash deploy/recruiting_chain.sh full --dry-run
#
# NOT ON THE TOP OF THE HOUR (Megan 2026-09-03). The 1am chain ran at 01:00 —
# the same minute as SIX other Lucy 2 agents that fire at :00 of every hour:
# applicant-push, resume-pushing, oat-processing, rc-autoread, hub-watch,
# card-scheduler. applicant-push and resume-pushing both log into AppStream, which
# is the exact contention this chain was built to end ("with the resume pusher
# also logging in, tripped Cloudflare" — see WHY A CHAIN above); the chain simply
# started in the same minute as the pusher every night. 01:10 clears all six. The
# 1pm chain, which has never had this problem, already sits at 13:00 with only the
# same hourly crowd — leave it until the 1am one is proven.
#
# TIME KNOB: edit StartCalendarInterval in
#   deploy/com.alphalete.recruiting-chain-1am.plist   (01:10)
#   deploy/com.alphalete.recruiting-chain-1pm.plist   (13:00)
# then re-install:
#   python -m automations.day_orchestrator.install_agent recruiting-chain-1am
set -u
cd "$(dirname "$0")/.." || exit 1

MODE="${1:-full}"
shift 2>/dev/null || true
EXTRA=("$@")

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/recruiting-chain-$(date +%Y%m%d-%H%M%S).log"

# Overlap guard: the 1pm chain must never start while the 1am one is somehow
# still going, and a manual run must not fight a scheduled one.
if pgrep -f "deploy/recruiting_chain.sh" | grep -qv "^$$\$"; then
    echo "[$(date)] recruiting-chain SKIPPED — a previous chain is still running" | tee -a "$LOG"
    exit 0
fi

case "$MODE" in
  full)    STEPS=("funnel_board_hourly.sh" "indeed_source_report.sh" "ad_sales_board.sh") ;;
  refresh) STEPS=("indeed_source_report.sh" "ad_sales_board.sh") ;;
  *) echo "unknown mode '$MODE' (want: full | refresh)" | tee -a "$LOG"; exit 2 ;;
esac

# HUB PILL. The chain is one card ("Recruiting Chain") that colours in two
# PHASES: amber after the 1am chain, green after the 1pm refresh. Both passes
# publish under the SAME report id, with DIFFERENT names -- the card is
# phase_runs, which counts DISTINCT names, so re-running the 1am chain counts
# once and can never tick the afternoon's box.
#
# Before this the wrapper published nothing at all. The steps each published
# their own run, but the chain itself was invisible, so hub_coverage auto-carded
# the two PLISTS instead and the Hub carried two permanently-white cards reading
# "scheduled 1:00 AM, no run logged" every day while the chain ran perfectly
# (Megan 2026-09-01: "recruiting chain is on here twice? also erroring").
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
case "$MODE" in
  full)    PHASE_NAME="Recruiting Chain - 1 AM full (funnel > indeed > ad sales)" ;;
  refresh) PHASE_NAME="Recruiting Chain - 1 PM refresh (indeed > ad sales)" ;;
esac
# A --dry-run rehearsal publishes nothing: it delivered no data, and a green
# pill for a rehearsal is the same lie as a green pill for a skipped run.
PUBLISH=1
case " ${EXTRA[*]:-} " in *" --dry-run "*) PUBLISH=0 ;; esac

REPORTED=0
_publish() {  # _publish <status>
    REPORTED=1
    [ "$PUBLISH" -eq 1 ] || return 0
    # SAY whether the row landed. publish_done returns False and raises nothing
    # when the Sheet write fails, so a card that stays white looked identical to
    # a chain that never ran — which is how the clean 13:00 pass on 2026-09-03
    # went unnoticed. One line in the log now names it. (Megan 2026-09-03)
    "$VENV_PY" -c "import sys
from automations.day_orchestrator import hub_publish
ok = hub_publish.publish_done('recruiting_chain', sys.argv[1], sys.argv[2])
print('hub pill: %s (%s)' % ('published' if ok else 'NOT PUBLISHED', sys.argv[2]))" \
        "$PHASE_NAME" "$1" >> "$LOG" 2>&1 || true
}

# A CHAIN THAT DIES HAS TO SAY SO (Megan 2026-09-02). Two nights running, the
# chain was killed mid-step and published NOTHING, so the card read "scheduled
# 1:00 AM, no run logged" -- the same thing it says when a job never fired at
# all. Those are opposite problems and they must not look identical: one is a
# missing agent, the other is a run that started and was cut off. This trap reds
# the card on any exit that did not already report itself, so the next morning
# says "failed" and points at the log. Deliberately installed AFTER the overlap
# guard's exit, which still publishes nothing: a skipped pass delivered no data
# and must never paint a colour of any kind.
trap '[ "$REPORTED" -eq 1 ] || _publish failed' EXIT
trap 'exit 143' TERM HUP INT   # so a signalled chain still runs the EXIT trap

# HOLD THE MACHINE AWAKE FOR THE LENGTH OF THE CHAIN (Megan 2026-09-01).
# On 2026-09-01 the 1am chain fired dead on time (01:00:03), got through one of
# funnel_board's 14 managers, and vanished at 01:00:57 -- no exit line, empty
# stderr, nothing after. That is not a crash, it is a machine going to sleep
# underneath a running job. The morning data was not lost (the mini re-ran all
# three reports at 06:45) but the chain never finished, and the 1pm pass, which
# skips funnel_board and is short, ran fine at 13:00:01 -- which is why only the
# overnight one looked broken.
#
# com.alphalete.keep-awake IS loaded here, but it asserts `caffeinate -s`, and
# -s holds ONLY ON AC POWER. That was written for the mini. Lucy 2 is a LAPTOP,
# so the fleet-wide assertion buys this chain nothing the moment it is on
# battery. -i asserts against IDLE sleep whatever the power source, and `-w $$`
# ties it to this script: it releases itself when the chain exits, however it
# exits, so a wedged chain cannot leave the machine pinned awake all night.
#
# This cannot save a chain from a CLOSED LID -- clamshell sleep is not an idle
# assertion and no flag overrides it. If the overnight run keeps dying, the lid
# (or AC) is the next thing to check, not this.
if [ -x /usr/bin/caffeinate ]; then
    /usr/bin/caffeinate -i -w $$ >/dev/null 2>&1 &
fi

# FREE THE SHARED CHROME PROFILE BEFORE STEP 1 (Megan 2026-09-02).
# The chain fired dead on time on 9/1 (01:00:03) and 9/2 (01:00:02), got into
# funnel_board's AppStream login both nights -- 9/2's last line is "-> Filling
# password" -- and then vanished: no exception, no "<-- exit=" line, and
# recruiting-chain-1am.err EMPTY, 0 bytes. That is a browser that never came up,
# not code that failed.
#
# Every OTHER launcher that runs outside the 4am window already guards for this:
# texas_de_brazil_745, stf_field_check_11pm, raf/carlos_captainship_*,
# due_diligence_harvest, att_churn_daily. The chain -- the one job that runs at
# 1 AM, as far from the 4am window as it is possible to be -- was the only one
# that did not. Both paths that DO succeed do it: the orchestrator (run.py:331)
# and `lucy rerun` (mini_control.py:553), which is exactly why the same
# funnel_board that died at 01:00 ran clean at 09:27 by hand.
#
# --unstick is the half a bare `--close` was missing: --close removes a HUMAN's
# Chrome, unstick_profile removes OUR OWN browser orphaned by an earlier killed
# report, which still holds the profile's ProcessSingleton. It is orphans-only
# (PPID 1), so it cannot touch a live report's Chrome. Once per chain, not per
# step: all three steps share the one profile.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close --unstick \
    >> "$LOG" 2>&1 || true

echo "[$(date)] recruiting-chain START mode=$MODE steps=${#STEPS[@]}" | tee -a "$LOG"
FAILED=()
# PER-STEP WEDGE GUARD (Megan 2026-09-03). The 1 AM chain "vanished" three
# nights running -- 9/1, 9/2, 9/3 -- and the diagnosis it got twice (the machine
# slept) was WRONG: `lucy diag` on Lucy 2 reads `SleepDisabled=1` on AC power. It
# never died. It HUNG, inside step 1, and a hang leaves exactly the fingerprint a
# death does: the log stops mid-step with no `<--` line, launchd's .err is 0
# bytes, and the EXIT trap below never fires -- because the process never exits.
# 9/3's log is five lines ending at `--> funnel_board_hourly.sh`; funnel_board's
# own log ends one line after `Sheets auth`, before `existing log:`.
#
# That is the failure applicant_push.sh already documents in as many words:
# launchd keeps ONE instance per label, so a hung tick swallows every tick after
# it AND leaves the agent "loaded", i.e. healthy-looking. funnel_board_backstop
# carries the same 30-minute watchdog. This chain -- three browser+Sheets steps
# at 1 AM with nobody watching -- was the one that had no cap at all.
#
# Per STEP, not per chain: the cap has to name which step wedged, and killing the
# chain wholesale would lose the two steps that were fine. 40 min is well clear of
# the real numbers (funnel ~3 min, indeed 11 min, ad_sales 25 min on 9/3) so this
# only ever fires on a genuine wedge. A killed step is a FAILED step, so the chain
# still finishes, still publishes, and tomorrow's 1 AM is not blocked behind it.
STEP_MAX_S=${RECRUITING_CHAIN_STEP_MAX_S:-2400}

for s in "${STEPS[@]}"; do
    echo "[$(date)] --> $s" | tee -a "$LOG"
    START=$(date +%s)
    if [ "${#EXTRA[@]}" -gt 0 ]; then
        bash "deploy/$s" "${EXTRA[@]}" >> "$LOG" 2>&1 &
    else
        bash "deploy/$s" >> "$LOG" 2>&1 &
    fi
    STEP_PID=$!
    WAITED=0
    while kill -0 "$STEP_PID" 2>/dev/null && [ "$WAITED" -lt "$STEP_MAX_S" ]; do
        sleep 5
        WAITED=$((WAITED + 5))
    done
    if kill -0 "$STEP_PID" 2>/dev/null; then
        echo "[$(date)] WEDGE GUARD: $s still running after ${STEP_MAX_S}s — killing it" | tee -a "$LOG"
        # The wrapper only forwards its child's exit, so kill the MODULE too or
        # the python keeps the run.lock and the AppStream profile after we move on.
        kill -TERM "$STEP_PID" 2>/dev/null
        sleep 20
        kill -KILL "$STEP_PID" 2>/dev/null
        case "$s" in
            funnel_board_hourly.sh)  pkill -f "automations.funnel_board.run" 2>/dev/null ;;
            indeed_source_report.sh) pkill -f "automations.indeed_source_report" 2>/dev/null ;;
            ad_sales_board.sh)       pkill -f "automations.ad_sales_board.run" 2>/dev/null ;;
        esac
        wait "$STEP_PID" 2>/dev/null
        RC=124
    else
        wait "$STEP_PID"
        RC=$?
    fi
    echo "[$(date)] <-- $s exit=$RC ($(( $(date +%s) - START ))s)" | tee -a "$LOG"
    # Keep going on failure: skipping the rest would silently cost a whole day
    # of data on reports that do not depend on each other's success.
    [ $RC -ne 0 ] && FAILED+=("$s")
done

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "[$(date)] recruiting-chain FINISHED with ${#FAILED[@]} failure(s): ${FAILED[*]}" | tee -a "$LOG"
    _publish failed
    exit 1
fi
echo "[$(date)] recruiting-chain FINISHED clean" | tee -a "$LOG"
_publish success
exit 0
