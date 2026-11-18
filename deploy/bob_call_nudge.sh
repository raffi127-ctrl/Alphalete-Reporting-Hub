#!/bin/bash
# Hourly 4pm-9pm machine local (Lucy 1 is Central) — DM the offices whose BOB
# calls have not been logged, once each has reached 6pm in ITS OWN timezone.
# launchd: com.alphalete.bob-call-nudge.
#
# WHY HOURLY FOR A 6PM NUDGE: 6pm in Los Angeles is 8pm in Chicago, so one
# fire on this machine's clock can only ever be 6pm in one zone. The hour is
# decided per office inside the run, and each owner is DM'd once a day.
#
# THIS SENDS REAL SLACK DMs. The run refuses the ones that matter rather than
# this wrapper: an unreadable BOB mark nudges NOBODY (otherwise every office
# gets DM'd nightly about calls they made), a failed ApplicantStream read is
# never treated as "nobody called", and an owner already nudged today is
# skipped.
#
# Manual: bash deploy/bob_call_nudge.sh --dry-run
#
# CADENCE: the plist's StartCalendarInterval. TIME KNOB is there, not here.
set -u
cd "$(dirname "$0")/.." || exit 1

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# Needs a browser (ApplicantStream), so the venv has to be the one with it.
VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import patchright" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with patchright — cannot read ApplicantStream" \
        >> "$LOG_DIR/bob-call-nudge.skip.log"
    exit 1
fi

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Two at once would read the same pages twice and could double-DM between the
# marker being read and written.
if pgrep -f "automations.second_round_contacts.bob_nudge" > /dev/null 2>&1; then
    echo "[$(date)] bob_call_nudge already running — skipping this fire" \
        >> "$LOG_DIR/bob-call-nudge.skip.log"
    exit 0
fi

# Never run while the 7pm pass is mid-flight: both read the same pages, and a
# nudge built from a half-done read is a nudge about the wrong people.
if pgrep -f "automations.second_round_contacts.run" > /dev/null 2>&1; then
    echo "[$(date)] the 2nd-round pass is running — skipping this fire" \
        >> "$LOG_DIR/bob-call-nudge.skip.log"
    exit 0
fi

# --dry-run anywhere in the args wins; otherwise this DMs for real.
MODE="--send"
case " $* " in *" --dry-run "*) MODE="" ;; esac

LOG_FILE="$LOG_DIR/bob-call-nudge-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] BOB call nudge starting (mode: ${MODE:-dry-run}, extra args: ${*:-none})" > "$LOG_FILE"

# A standalone LaunchAgent publishes to the Hub itself: the orchestrator only
# publishes what IT runs, so without this a silent miss and a clean run look
# identical on the Hub (feedback_launchd_reports_must_publish).
if [ -n "$MODE" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('bob_call_nudge','BOB Call Nudge')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.second_round_contacts.bob_nudge $MODE "$@" >> "$LOG_FILE" 2>&1
ST=$?

if [ -n "$MODE" ]; then
    STATUS=success
    [ "$ST" -ne 0 ] && STATUS=failed
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('bob_call_nudge','BOB Call Nudge','$STATUS')" >> "$LOG_FILE" 2>&1 || true
fi

echo "[$(date)] finished, exit $ST" >> "$LOG_FILE"
exit $ST
