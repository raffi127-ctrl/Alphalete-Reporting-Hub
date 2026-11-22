#!/bin/bash
# Daily 9:15pm (machine-local) — write WHO WAS MARKED NO SHOW in
# ApplicantStream onto this office's onboarding board.
# launchd: com.alphalete.icd-onboarding-no-shows.
#
# WHY ITS OWN CLOCK AND NOT THE HOURLY RUN. This is the SEVEN-page calendar
# walk. The hourly board run deliberately stopped walking the calendar when the
# two-page Retention Report turned out to answer its question (Megan,
# 2026-11-09), and putting the walk back on an hourly clock would undo that.
# The answer only changes when a recruiter marks a radio, so once a day is
# enough (Megan, 2026-11-16: "run it daily").
#
# WHY THE EVENING. The training day has to have happened and somebody has to
# have marked it. The evening is after the office has closed and before the next
# morning's sends -- Blue Ink goes out at 7:30am, and this is the column that
# stops it mailing documents to somebody who did not come.
#
# WHAT IT WRITES. One column, `Showed Up`, and only forwards: blank -> No Show
# -> a date. A blank is NOT a no show (nobody has said yet), and a date beats a
# No Show, because somebody marked absent on Monday walking in on the Tuesday
# is the case the board exists to survive.
#
# SENDS NOTHING. It reads ApplicantStream and writes its own board.
#
# Manual: bash deploy/icd_onboarding_no_shows.sh
# Preview: bash deploy/icd_onboarding_no_shows.sh --dry-run
MODE="write"
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import patchright" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with patchright — cannot read ApplicantStream" \
        >> output/logs/icd-onboarding-no-shows.skip.log
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never overlap with the hourly board run: both drive the same ApplicantStream
# profile, and the second to arrive finds it held. Skipping is right -- the
# next fire is tomorrow and nothing has been missed that a day will not catch.
if pgrep -f "automations.icd_onboarding.run" > /dev/null 2>&1; then
    echo "[$(date)] icd_onboarding already running — skipping the no-show walk" \
        >> output/logs/icd-onboarding-no-shows.skip.log
    exit 0
fi

ARGS=(--only no_shows)
[ "$MODE" = "write" ] && ARGS+=(--write)
case " $* " in *" --dry-run "*) ARGS=(--only no_shows) ;; esac

LOG_FILE="output/logs/icd-onboarding-no-shows-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] no-show walk starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.icd_onboarding.run ${ARGS[@]+"${ARGS[@]}"} "$@" \
    >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] no-show walk finished exit=$ST" >> "$LOG_FILE"

# Its own heartbeat row, so a walk that stops firing is noticed. NOT the
# board's: the hourly run beats under `icd_onboarding` per machine, and sharing
# that id would let one of them keep the row green while the other had stopped
# -- which is exactly how Contact Added and BG Status sat at 0 for days
# (2026-11-11). A sub-step gets its own beat or no beat at all.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat icd_onboarding_no_shows --exit "$ST" >> "$LOG_FILE" 2>&1 || true

# NO HUB ACTIVITY ROW, on purpose. This is a sub-step of the ICD Onboarding
# Board card, not a report of its own -- the same shape as
# blueink-completed-sweep, which fires every two hours and belongs to no card.
# The hourly run publishes that card; a second publisher would make the card
# say whichever of the two finished last.
exit 0
