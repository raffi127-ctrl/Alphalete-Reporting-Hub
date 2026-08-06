#!/bin/bash
# DD / Organization Bulletin — weekly Thursday SEND, on the mini (Lucy 1).
#
# WHY IT HAS ITS OWN AGENT (Eve 2026-07-30): this report is READ-ONLY. Nothing in
# it rolls or fills the 'Org DDs Ongoing Report' tab — Eve opens the week's column
# by hand, and she has until 10am Central to do it. In the 4am batch the send fired
# hours BEFORE that, so the newest column was still last week's and the bulletin
# republished a week that had already gone out (7.19 went out twice, 7/23 and
# 7/30). Moving it here puts the send AFTER her fill window.
#
# REVIEWED SINCE 2026-08-06 (Eve). Nothing mails itself any more: each pass posts
# the week's PDF link to #revision-emails once, and only EVELYN's checkmark
# releases it. Jolie approves the other three reports in that channel; on this
# one her reaction does nothing — see APPROVERS in review_gate.py.
#
# launchd fires passes Thursday 10:30-13:00 Central, every 25 min. Every pass
# runs the same three steps, all idempotent:
#   --post          builds the pages, uploads the PDF, posts the link ONCE a
#                   week. HOLDS silently while the tab's newest column is not
#                   the Sunday that just ended (Eve fills it by hand, deadline
#                   10am Central), so a pass before her fill posts nothing and
#                   the next one picks it up.
#   --check --send  mails it the moment an authorised checkmark is there. The
#                   thread reply is the once-a-week lock, read from Slack rather
#                   than a local file so a second machine cannot double-send.
#   --remind        nudges once if it is still unapproved after 3h.
# The last pass of the day also runs --close-day, so a Thursday nobody approved
# says so in the thread instead of ending in silence.
#
# A correction after the link is out: `review_gate.py --refresh` — it rebuilds
# and OVERWRITES the PDF in Drive, so the link Evelyn already has open shows the
# new version. Never a second post.
#
# SOFT LAUNCH (Megan 2026-07-24): without --distro the send goes to the 4-person
# group (Megan, Eve, Carlos, Raf) and posts NOTHING to Slack. To go full-org, add
# --distro to the CHECK_ARGS below — that is a deliberate one-line change.
#
# Manual dry run (nothing posted, nothing sent):
#   bash deploy/dd_bulletin_thu.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.review_gate" > /dev/null 2>&1 \
   || pgrep -f "automations.override_bulletin.send" > /dev/null 2>&1; then
    echo "[$(date)] dd-bulletin SKIPPED — previous pass still running"
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

GATE=(automations.override_bulletin.review_gate)
# FULL-ORG, unchanged from the 2026-07-31 go-live: --distro makes the gate send
# `--dd --send --notify` — both contact groups ("Alphalete Org Owners" +
# "Bulletins") + the 3 Slack channels, alerting #claudecorrections on a data gap
# rather than refusing. What the review gate adds is WHO decides it goes: Evelyn's
# checkmark, instead of the clock. Drop --distro to fall back to the 4-person
# soft-launch group. A stale/empty week still HARD-blocks (never republishes).
CHECK_ARGS=(--check --send --distro)

LOG_FILE="$LOG_DIR/dd-bulletin-$(date +%Y-%m-%d-%H%M%S).log"

if [ "${1:-}" = "--dry" ]; then
    # Build the pages + PDF and stop. Nothing posted, nothing uploaded, nothing
    # mailed — the one command that is safe to run by hand on any machine.
    echo "[$(date)] dd-bulletin DRY (build only)" > "$LOG_FILE"
    "$VENV_PY" -u -m "${GATE[@]}" --pdf-only >> "$LOG_FILE" 2>&1
    ST=$?
    echo "[$(date)] dd-bulletin finished exit=$ST" >> "$LOG_FILE"
    cat "$LOG_FILE"
    exit $ST
fi

echo "[$(date)] dd-bulletin starting (gated: post -> check -> remind)" > "$LOG_FILE"

# 1. post the week's link (idempotent; holds while the tab is unfilled)
"$VENV_PY" -u -m "${GATE[@]}" --post >> "$LOG_FILE" 2>&1
ST=$?

# 2. send it if Evelyn has ticked it. Exit 1 just means "not approved yet", which
#    is the normal state of most passes — only a non-0/1 code is a real failure.
if [ "$ST" -eq 0 ]; then
    "$VENV_PY" -u -m "${GATE[@]}" "${CHECK_ARGS[@]}" >> "$LOG_FILE" 2>&1
    CK=$?
    [ "$CK" -gt 1 ] && ST=$CK
fi

# 3. nudge once after 3h, and on the last pass say so if nobody approved.
"$VENV_PY" -u -m "${GATE[@]}" --remind >> "$LOG_FILE" 2>&1 || true
if [ "$(date +%H)" -ge 13 ]; then
    "$VENV_PY" -u -m "${GATE[@]}" --close-day >> "$LOG_FILE" 2>&1 || true
fi

echo "[$(date)] dd-bulletin finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub card ONLY on a pass that actually emailed — holding for the
# tab, or waiting on the checkmark, is the normal state of most passes, and
# marking those green would make "nobody approved it" look like a clean run. A
# failure always publishes. Quiet card = it hasn't gone out yet, which is true.
# [[feedback_launchd_reports_must_publish]]
if [ "$ST" -ne 0 ]; then
    _PUB=failed
elif grep -q "^emailed " "$LOG_FILE"; then
    _PUB=success
else
    _PUB=""
    echo "[$(date)] held (nothing emailed) — card left alone" >> "$LOG_FILE"
fi
[ -n "$_PUB" ] && "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('dd_bulletin','DD / Organization Bulletin','$_PUB')" >> "$LOG_FILE" 2>&1 || true

# --- Up and Coming RCs and NCs — the EMAIL-ONLY companion sent right after the DD
# bulletin (Megan 2026-07-31). It reuses the DD data and stays in LOCK-STEP: the
# pass that sends the DD bulletin sends this too, every other pass holds it.
#
# That lock-step now runs through the gate. It used to derive its args from the
# DD's ARGS and fire on every pass, self-guarding on its own week marker; with the
# DD waiting on Evelyn's checkmark, firing unconditionally would mail the
# companion to the whole org on a Thursday nobody ever approved the bulletin.
# So it runs ONLY on the pass where the DD actually went out, and mirrors the
# gate's mode rather than a variable the gate no longer defines.
case " ${CHECK_ARGS[*]} " in
    *" --distro "*) RCS_ARGS=(--rcs-ncs --send --notify) ;;
    *)              RCS_ARGS=(--rcs-ncs --test --send) ;;
esac
_RPUB=""
if [ "$_PUB" = "success" ]; then
    echo "[$(date)] rcs-ncs starting (mode: ${RCS_ARGS[*]})" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.override_bulletin.send "${RCS_ARGS[@]}" >> "$LOG_FILE" 2>&1
    RST=$?
    echo "[$(date)] rcs-ncs finished exit=$RST" >> "$LOG_FILE"
    if [ "$RST" -ne 0 ]; then
        _RPUB=failed
    elif grep -q "^emailed .*Up and Coming RCs and NCs" "$LOG_FILE"; then
        _RPUB=success
    fi
else
    echo "[$(date)] rcs-ncs held — the DD bulletin did not send on this pass" >> "$LOG_FILE"
fi
[ -n "$_RPUB" ] && "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('rcs_ncs','Up and Coming RCs and NCs','$_RPUB')" >> "$LOG_FILE" 2>&1 || true

# A held pass exits 0 — a correct hold, not a failure; the next pass tries again.
exit $ST
