#!/bin/bash
# 7pm (machine-LOCAL) — the third 2nd-round scan of the day, plus the
# end-of-day cleanup. RUNS ON LUCY 1 (the box holding the reception accounts'
# contacts tokens). launchd: com.alphalete.second-round-contacts-evening.
#
# WHY A LAUNCHAGENT AND NOT THE 4am BATCH. Raf wants the scan at 6am, 11:30am
# and 7pm (2026-11-17). The first two are scheduler entries
# (second_round_contacts, second_round_contacts_pm). A 7pm not_before is not
# allowed in the batch -- it would keep every machine's orchestrator alive till
# 8pm and delay every stuck-report alert with it, which
# test_schedule_config.py blocks on purpose.
#
# TWO STEPS, IN ORDER:
#   1. the ADDS pass  -- any second round marked since 11:30 lands in the
#      owner's reception contacts.
#   2. the CLEANUP    -- `--audit --evening`: a second round that happened
#      TODAY and was marked neither "Second Interviews Showed Up" nor
#      "Offered Job From Second Round" comes back out. They are not coming.
#
# THE CLEANUP ONLY EVER RUNS IN THE EVENING. At 6am and 11:30 a blank means
# nobody has marked it yet, which is the same rule the onboarding board lives
# by -- so no earlier pass passes --evening, and nothing here guesses at a day
# that is still running.
#
# Step 2 runs even if step 1 fails: the removal reads ApplicantStream itself
# and does not depend on anything step 1 wrote.
#
# TIME KNOB: StartCalendarInterval in
# com.alphalete.second-round-contacts-evening.plist, not here.
#
# Manual:  bash deploy/second_round_contacts_evening.sh
# Preview: bash deploy/second_round_contacts_evening.sh --dry-run
MODE="write"
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"
# NOTE: no HEADLESS=1 — headless trips a Cloudflare re-challenge on the
# AppStream login.

case " $* " in *" --dry-run "*) MODE="dry" ;; esac
WRITE=()
[ "$MODE" = "write" ] && WRITE=(--write)

if pgrep -f "automations.second_round_contacts.run" > /dev/null 2>&1; then
    echo "[$(date)] second-round-contacts-evening SKIPPED — a pass is still running" \
        >> output/logs/second-round-contacts-evening.skip.log
    exit 0
fi

LOG_FILE="output/logs/second-round-contacts-evening-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] evening pass starting (mode=$MODE)" > "$LOG_FILE"

# A STANDALONE LaunchAgent bypasses the orchestrator, so it has to report
# itself or the card stays grey and a clean run looks exactly like a silent
# miss (standing rule, 2026-07-14). Same report_id as the 6am and 11:30am
# scheduler passes: it is one card with three clocks. Skipped on --dry-run so
# a preview never marks the card as ran.
if [ "$MODE" = "write" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('linkedin-2nd-round-contacts','2nd rounds -> owners reception contacts')" >> "$LOG_FILE" 2>&1 || true
fi

echo "--- step 1: adds ---" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.second_round_contacts.run \
    ${WRITE[@]+"${WRITE[@]}"} >> "$LOG_FILE" 2>&1
ADD=$?
echo "--- step 1 exit=$ADD ---" >> "$LOG_FILE"

echo "--- step 2: end-of-day cleanup ---" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.second_round_contacts.run --audit --evening \
    ${WRITE[@]+"${WRITE[@]}"} >> "$LOG_FILE" 2>&1
CLEAN=$?
echo "--- step 2 exit=$CLEAN ---" >> "$LOG_FILE"

ST=0
[ "$ADD" -ne 0 ] && ST="$ADD"
[ "$CLEAN" -ne 0 ] && ST="$CLEAN"
echo "[$(date)] evening pass finished exit=$ST" >> "$LOG_FILE"

if [ "$MODE" = "write" ]; then
    _PUB="success"; [ "$ST" -ne 0 ] && _PUB="failed"
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('linkedin-2nd-round-contacts','2nd rounds -> owners reception contacts','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

# Its own heartbeat, so a pass that stops firing is noticed. NOT the
# scheduler entries' id: sharing it would let the 6am run keep the row green
# while this one had stopped.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat second_round_contacts_evening --exit "$ST" >> "$LOG_FILE" 2>&1 || true
exit 0
