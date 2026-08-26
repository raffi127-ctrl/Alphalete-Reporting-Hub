#!/bin/bash
# Every 2 hours, 8am-8pm (machine-local; Lucy 2 is Central) — tick the "Blue
# Ink" checkbox for anyone whose packet has been SIGNED since the last look.
# launchd: com.alphalete.blueink-completed-sweep.
#
# SENDS NOTHING. `--sync-completed` only reads Blue Ink's Completed list and
# ticks boxes, so an accident here costs a checkbox, never a packet.
#
# Why a sweep at all: the Monday 7:30 run marks who was SENT, but people sign
# whenever they get round to it. Without this the checkboxes would sit stale
# until the following Monday.
#
# It reads the Completed column in ONE page load (scrolled back ~3 weeks) and
# matches names, rather than searching per person — a search is ~10s, so
# per-person would cost 50+ people the best part of ten minutes every fire.
#
# Manual: bash deploy/blueink_completed_sweep.sh
#
# CADENCE: the plist's StartCalendarInterval array. TIME KNOB is there, not here.
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
    echo "[$(date)] no venv python with patchright — cannot read Blue Ink" \
        >> output/logs/blueink-completed.skip.log
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never overlap: two sweeps would drive the same browser profile.
if pgrep -f "automations.blueink_docs.run" > /dev/null 2>&1; then
    echo "[$(date)] blueink_docs already running — skipping this sweep" \
        >> output/logs/blueink-completed.skip.log
    exit 0
fi

LOG_FILE="output/logs/blueink-completed-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Blue Ink completed-sweep starting" > "$LOG_FILE"
"$VENV_PY" -u -m automations.blueink_docs.run --sync-completed "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] Blue Ink completed-sweep finished exit=$ST" >> "$LOG_FILE"

# Deliberately NOT published to the Hub: this fires seven times a day and would
# drown the card's run history, hiding the one run that matters — Monday's
# send. A failure here leaves checkboxes stale, nothing worse.
#
# Not publishing was only ever meant to hide the OUTCOME of a pass, not the
# fact that passes are happening at all — and with no Activity row, nothing
# could tell that this agent had stopped firing (Megan 2026-08-26). The
# heartbeat below is one overwritten row, so seven fires a day still drown
# nothing, and the 10-minute watcher alerts if the sweep goes quiet for more
# than five hours inside its window. Best-effort: it cannot change the exit
# code, and a pass skipped by the pgrep guard above deliberately does NOT beat
# (the run it stepped aside for will).
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat blueink_completed_sweep --exit "$ST" >> "$LOG_FILE" 2>&1 || true

exit 0
