#!/bin/bash
# Monday 7:45am (machine-local; Lucy 3 is Central) — Digi Docs: add this week's
# new starts to OwnerVille, then generate and mail each of them their document
# bundle. Runs on Lucy 3 via launchd (com.alphalete.digi-docs-monday).
#
# Runs automations.digi_docs.run --both --live, which is two phases in order:
#   1. ADD    every eligible person on the newest "D2D OBCL <m.d>" tab (every
#             chart on it) who is not in OwnerVille yet. Mails nobody.
#   2. SEND   for each rep still showing ONBOARDING DOCUMENTS = REQUIRED ACTION,
#             generate the bundle (which IS the send — OwnerVille mails it),
#             tick the BG/drug attestations, then tint their Digi Docs cell.
#
# Batched on purpose, not a full add-then-send cycle per person: the two phases
# live on different pages, and if the send phase dies halfway everyone still
# EXISTS in OwnerVille rather than the roster being half-added.
#
# 7:45am Monday is Megan's call — alongside Blue Ink's 7:30 on Lucy 2. Same
# cohort, same morning, different machines so they do not contend. The 8:30
# headshots job only posts a Slack thread, so it is not an OwnerVille
# collision.
#
# SENDING IS IRREVERSIBLE — generating a bundle mails a nine-document contract
# packet and there is no unsend. The module defaults to dry-run; this WRAPPER
# is what passes --live. To preview what a fire would do:
#
#   bash deploy/digi_docs_monday.sh --dry-run
#
# CADENCE: the plist fires Monday 07:45 machine-local. TIME KNOB: edit
# StartCalendarInterval in the plist, not this wrapper.
set -u
cd "$(dirname "$0")/.." || exit 1
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

# --dry-run anywhere in the args wins and is NOT forwarded (run.py has no such
# flag — dry is simply the absence of --live). Everything else passes through.
MODE="--both --live"
FWD=()
for _a in "$@"; do
    if [ "$_a" = "--dry-run" ]; then MODE="--both"; else FWD+=("$_a"); fi
done

LOG_FILE="$LOG_DIR/digi-docs-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Digi Docs starting (mode: $MODE, extra args: ${FWD[*]:-none})" > "$LOG_FILE"

if [ "$MODE" = "--both --live" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('digi_docs','Digi Docs')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.digi_docs.run $MODE ${FWD[@]+"${FWD[@]}"} >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Digi Docs finished exit=$ST" >> "$LOG_FILE"

# Publish either way so a blocked run is visible on the Hub instead of leaving
# the card grey. [[feedback_launchd_reports_must_publish]]
if [ "$MODE" = "--both --live" ]; then
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('digi_docs','Digi Docs','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

exit 0
