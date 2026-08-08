#!/bin/bash
# Override Bulletin — weekly Friday SEND, on the mini (Lucy 1 = Raf's org logins).
#
# GATED (Megan 2026-08-07: "it should mirror the DD one for eve's approval"). This
# no longer emails on the clock. It runs the review gate
# (automations.override_bulletin.override_gate), which posts the week's bulletin
# link in #revision-emails and mails the FULL distro (every Slack channel + both
# contact groups) ONLY once Eve (Evelyn) reacts :white_check_mark:. Same shape,
# approver, channel and Drive token as the DD bulletin's dd_bulletin_thu.sh.
#
# The gate RENDERS OUR OWN fill — the 'Copy of Org Overrides Ongoing Report'
# (sandbox) tab that override_bulletin.run fills from the real sources — NOT the
# VA's live tab (that is a reference, not a source). send.py refuses a week that
# isn't filled and records the week it sent so the q25m passes never double-mail.
# If the copy tab isn't filled yet, --post HOLDS quietly until the fill agent
# populates it.
#
# HUB PILL — 2-phase pill (card daily_runs:2): ORANGE once the link is posted for
# Eve (1/2), GREEN once she approves and it sends (2/2). Both passes publish
# success under the SAME card id (override_bulletin), so a week that never gets
# approved stays orange (not a false green); an approved-but-failed send publishes
# 'failed' (which also alerts #claudecorrections).
#
# launchd fires passes Friday 10:30-13:00 CST (after the ~10am fill window), q25m.
# TIME KNOB: edit StartCalendarInterval in the plist.
#
# SOFT-LAUNCH FALLBACK: to go back to the 4-person email preview (no Slack, no
# gate), drop --distro from CHECK_ARGS below — the gate then sends `--test --send`.
#
# Manual dry run (build the PDF only, nothing posted/sent):
#     bash deploy/override_bulletin_send_fri.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.override_gate" > /dev/null 2>&1; then
    echo "[$(date)] override-bulletin-send SKIPPED — previous pass still running"
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

GATE=(automations.override_bulletin.override_gate)
# FULL-ORG: --distro makes the gate send `send.py --send` — every Slack channel +
# both contact groups ("Alphalete Org Owners" + "Bulletins"). Drop --distro to
# fall back to the 4-person soft-launch email group. An unfilled week still HOLDS
# (never posts a blank/wrong week); a wrong week never mails.
CHECK_ARGS=(--check --send --distro)

LOG_FILE="$LOG_DIR/override-bulletin-send-$(date +%Y-%m-%d-%H%M%S).log"

_pub() {  # _pub <report_id> <name> <status>
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('$1','$2','$3')" >> "$LOG_FILE" 2>&1 || true
}

if [ "${1:-}" = "--dry" ]; then
    # Build the page + PDF and stop. Nothing uploaded, posted, or mailed — the one
    # command that is safe to run by hand on any machine.
    echo "[$(date)] override-bulletin-send DRY (build only)" > "$LOG_FILE"
    "$VENV_PY" -u -m "${GATE[@]}" --pdf-only >> "$LOG_FILE" 2>&1
    ST=$?
    echo "[$(date)] override-bulletin-send finished exit=$ST" >> "$LOG_FILE"
    cat "$LOG_FILE"
    exit $ST
fi

echo "[$(date)] override-bulletin-send starting (gated: post -> check -> remind)" > "$LOG_FILE"

# 1. post the week's link (idempotent; HOLDS while the copy tab is unfilled).
"$VENV_PY" -u -m "${GATE[@]}" --post >> "$LOG_FILE" 2>&1
ST=$?
# PHASE 1 (1/2 = orange): a real post landed this pass. A HOLD exits 0 but prints
# no "posted to" line, so it does NOT count phase 1 — the card stays blank until
# the link is actually up. A crash (non-zero) reds it.
if [ "$ST" -ne 0 ]; then
    _pub override_bulletin "Override Bulletin" failed
elif grep -q "✓ posted to" "$LOG_FILE"; then
    _pub override_bulletin "Override Bulletin" success
fi

# 2. send it if Eve has ticked it. Exit 1 just means "not approved yet" — the
#    normal state of most passes; only a non-0/1 code is a real failure.
if [ "$ST" -eq 0 ]; then
    "$VENV_PY" -u -m "${GATE[@]}" "${CHECK_ARGS[@]}" >> "$LOG_FILE" 2>&1
    CK=$?
    # PHASE 2 (2/2 = green): "✓ SENT" prints only on a send that actually went out
    # this pass (an already-sent week returns 0 quietly and does NOT re-publish, so
    # the count never exceeds 2). Same card id as phase 1 so the two count together
    # to green. A code >1 is approved-but-failed → 'failed' (also alerts Slack).
    if [ "$CK" -eq 0 ] && grep -q "✓ SENT" "$LOG_FILE"; then
        _pub override_bulletin "Override Bulletin" success
    elif [ "$CK" -gt 1 ]; then
        _pub override_bulletin "Override Bulletin" failed
        ST=$CK
    fi
fi

# 3. nudge once after 3h, and on the last pass say so if nobody approved.
"$VENV_PY" -u -m "${GATE[@]}" --remind >> "$LOG_FILE" 2>&1 || true
if [ "$(date +%H)" -ge 13 ]; then
    "$VENV_PY" -u -m "${GATE[@]}" --close-day >> "$LOG_FILE" 2>&1 || true
fi

echo "[$(date)] override-bulletin-send finished exit=$ST" >> "$LOG_FILE"
# A held pass (unfilled week, not-yet-approved) exits 0 — a correct hold, not a
# failure; the next scheduled pass simply tries again.
exit $ST
