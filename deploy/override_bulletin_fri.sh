#!/bin/bash
# Override Bulletin — weekly Friday FILL, on the mini (Lucy 1 = Raf's org logins).
# launchd fires passes 08:00-12:55 CST every Friday, q25-30m. The run resolves which
# week to fill from the ORG Override Summary itself and holds until that source has
# published the new week; once it fills, later passes no-op.
#
# Starts at 08:00 (was 09:00) because the review link has to be posted by 10:10 CST
# (Eve, 2026-08-21) and a run takes ~25-30 min — the pgrep guard below makes the
# effective cadence ~50 min, so the fill needs its first chances well before 09:30.
#
# SANDBOX ONLY: --tab defaults to "Copy of Org Overrides Ongoing Report", and
# fill.write_week REFUSES the live tab outright. Nothing is posted to Slack and
# no email is sent — that step isn't built and must never auto-send.
#
# CADENCE: Fridays only (Weekday 5 in the plist). TIME KNOB: edit
# StartCalendarInterval in deploy/com.alphalete.override-bulletin-fri.plist.
#
# Manual test (no write):  bash deploy/override_bulletin_fri.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.run" > /dev/null 2>&1; then
    echo "[$(date)] override-bulletin SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Writes the SANDBOX tab by default. Pass "--dry" to preview without writing.
#
# NO --force. It was here while the sandbox was dirty from build testing, but it
# defeats the whole point of the fill-gate: the run targets the newest week the
# ORG Override Summary carries, and that source LAGS — on Fri 2026-07-24 its
# newest was still 7.12, a week already filled. With --force every pass "refills"
# that finished week instead of holding for the one we actually want, overwriting
# good values with a fresh pull each time. Holding is the correct outcome until
# the summary publishes the new week. The sandbox was cleaned 2026-07-23
# (`run.py --clear-week`), so there is nothing left for --force to work around.
MODE="--write"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/override-bulletin-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] override-bulletin starting (mode: $MODE)" > "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# A HOLD (the Override Summary hasn't published the week yet) already exits 0
# inside run.py — a correct outcome, not a failure, so the next pass just tries
# again quietly. Anything else IS a failure and must surface: today (Fri
# 2026-07-24) two Tableau views stopped exporting, the run died, and this
# unconditional `exit 0` reported it as a clean pass, so nothing alerted and no
# email went out. Propagate the real status — a hold stays silent, a crash pages.
echo "[$(date)] override-bulletin finished exit=$ST" >> "$LOG_FILE"
# A HOLD exits 0 (correct — the Override Summary just hasn't published the week;
# stays quiet + keeps the testing/pink pill). A real FAILURE (non-zero) writes no
# Hub row otherwise, so the digest can't see it and nothing alerts. Publish
# 'failed' ONLY on a real failure → reds the card + the 10-min digest posts it to
# #claudecorrections. Skip on --dry preview. (Megan 2026-07-29)
# The FILL is prep, not a user-facing phase — the send wrapper's review gate owns
# the card's pill (phase 1 = built + posted for Eve, phase 2 = sent). But a fill
# FAILURE must still red the card: without a row here a crashed fill (two Tableau
# views stopped exporting on Fri 2026-07-24) is invisible and looks like a clean
# pass. So publish 'failed' ONLY on a real failure. A HOLD exits 0 and stays
# quiet. Skip on --dry preview. (Megan 2026-07-29)
if [ "$ST" -ne 0 ] && [ "${1:-}" != "--dry" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('override_bulletin','Override Bulletin','failed')" >> "$LOG_FILE" 2>&1 || true
fi
exit $ST
