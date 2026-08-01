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
# launchd fires passes Thursday 10:30-13:00 Central, every 25 min. The passes are
# safe to repeat, because the send is GATED three ways:
#   * dd_data blocks a stale week — if the newest column is not the Sunday that
#     just ended, it refuses rather than republish (send.py honours `blocking`),
#   * it records the week it sent, so a later pass never double-emails,
#   * a blocking data problem refuses the send outright.
# So a pass before Eve fills the tab holds quietly and the next one picks it up as
# soon as the column is there. TIME KNOB: edit StartCalendarInterval in the plist.
#
# SOFT LAUNCH (Megan 2026-07-24): `send --dd --test --send` emails the 4-person
# TEST_TO group (Megan, Eve, Carlos, Raf) and posts NOTHING to Slack. To go
# full-org (Slack + both contact groups), drop --test from ARGS below — that is a
# deliberate one-line change.
#
# Manual dry run (nothing sent):  bash deploy/dd_bulletin_thu.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.send" > /dev/null 2>&1; then
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

# send.py builds both pages itself (dd_send calls dd_build), so this one command
# is the whole report — no separate build step to keep in sync.
# FULL-ORG GO-LIVE (Megan 2026-07-31): --dd --send --notify = both contact groups
# ("Alphalete Org Owners" + "Bulletins") + the 3 Slack channels, and on any data
# gap (Credico pending / missing row) it alerts #claudecorrections and sends anyway
# rather than refusing. A stale/empty week still HARD-blocks (never republishes).
# The RCs/NCs companion below mirrors this → both go full to the org. To pull back
# to the 4-person soft-launch group, restore ARGS=(--dd --test --send).
ARGS=(--dd --send --notify)
[ "${1:-}" = "--dry" ] && ARGS=(--dd)

LOG_FILE="$LOG_DIR/dd-bulletin-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] dd-bulletin starting (mode: ${ARGS[*]})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.send "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] dd-bulletin finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub card ONLY on a pass that actually emailed — a stale-week or
# already-sent hold is the normal state of six of the seven passes, and marking
# those green would make "Eve never filled the tab" look like a clean run. A
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
# bulletin (Megan 2026-07-31). It reuses the DD data, so it self-guards the SAME
# three ways: a stale/empty week hard-blocks it, it records its own week (never
# double-emails), and it mirrors the DD's mode here (--test → the 4-person group,
# full → both contact groups). So it stays in lock-step: the pass that sends the
# DD bulletin sends this too, and every other pass holds it.
RCS_ARGS=("${ARGS[@]/--dd/--rcs-ncs}")
echo "[$(date)] rcs-ncs starting (mode: ${RCS_ARGS[*]})" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.override_bulletin.send "${RCS_ARGS[@]}" >> "$LOG_FILE" 2>&1
RST=$?
echo "[$(date)] rcs-ncs finished exit=$RST" >> "$LOG_FILE"
if [ "$RST" -ne 0 ]; then
    _RPUB=failed
elif grep -q "^emailed .*Up and Coming RCs and NCs" "$LOG_FILE"; then
    _RPUB=success
else
    _RPUB=""
fi
[ -n "$_RPUB" ] && "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('rcs_ncs','Up and Coming RCs and NCs','$_RPUB')" >> "$LOG_FILE" 2>&1 || true

# A held pass exits 0 — a correct hold, not a failure; the next pass tries again.
exit $ST
