#!/bin/bash
# Monday 7:30am (machine-local; Lucy 2 is Central) — send Blue Ink onboarding
# docs to the week's new starts, on Lucy 2, via launchd
# (com.alphalete.blueink-docs-monday).
#
# Runs automations.blueink_docs.run: read the newest dated "D2D OBCL <m.d>" tab
# on Raf's All in One Local Office workbook (BOTH stacked sections), drop anyone
# with a Final Status (quit / failed BGC / terminated / no show / rescheduling)
# or a Failed / Adverse Action BG Status, skip anyone already in the "Blue Ink
# Log" tab, and send each remaining person their packet.
#
# 7:30am Monday is Megan's call: that IS start day, and the dated tab is named
# for it (D2D OBCL 8.24 -> Monday 8/24), so the newest tab is always the right
# week. Expect Final Status to be BLANK for nearly everyone at that hour —
# nobody has started yet — which is exactly why the Final Status rule is a
# block-list and not "must be blank".
#
# SENDING IS IRREVERSIBLE — a Blue Ink bundle launches the moment it's created.
# The module defaults to dry-run; this WRAPPER is what passes --send. To preview
# what a fire would do, run it without the flag:
#
#   bash deploy/blueink_docs_monday.sh --dry-run
#
# CADENCE: the plist fires Monday 07:30 machine-local. TIME KNOB: edit
# StartCalendarInterval in the plist, not this wrapper.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

# Pick the interpreter that can actually drive a browser, rather than guessing
# a version: this repo's venv holds several, and patchright is not installed for
# all of them on every machine (3.9 has it on Lucy 2, 3.14 has it on Megan's
# laptop). Probing beats hardcoding.
VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import patchright" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with patchright — cannot drive Blue Ink" \
        >> "output/logs/blueink-docs.skip.log"
    exit 1
fi
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Two concurrent runs would double-send the same people — the ledger is only
# written after each bundle launches, so an overlapping fire reads a stale
# "already sent" map.
if pgrep -f "automations.blueink_docs.run" > /dev/null 2>&1; then
    echo "[$(date)] blueink_docs already running — skipping this fire" \
        >> "$LOG_DIR/blueink-docs.skip.log"
    exit 0
fi

# --dry-run anywhere in the args wins; otherwise this is the live send.
MODE="--send"
case " $* " in *" --dry-run "*) MODE="" ;; esac

LOG_FILE="$LOG_DIR/blueink-docs-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Blue Ink new-start docs starting (mode: ${MODE:-dry-run}, extra args: ${*:-none})" > "$LOG_FILE"

if [ -n "$MODE" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('blueink_docs','Blue Ink New Start Docs')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.blueink_docs.run $MODE "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Blue Ink new-start docs finished exit=$ST" >> "$LOG_FILE"

# Publish either way so a blocked run is visible on the Hub instead of leaving
# the card grey. [[feedback_launchd_reports_must_publish]]
if [ -n "$MODE" ]; then
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('blueink_docs','Blue Ink New Start Docs','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

exit 0
