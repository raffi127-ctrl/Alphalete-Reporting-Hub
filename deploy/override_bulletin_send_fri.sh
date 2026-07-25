#!/bin/bash
# Override Bulletin — weekly Friday SEND, on the mini (Lucy 1).
#
# SOFT LAUNCH (Megan 2026-07-25): this runs `send --test --send` — it emails the
# rendered bulletin to the 4-person TEST_TO group (Megan, Eve, Carlos, Raf) and
# posts NOTHING to Slack. It is a full week of preview to the leaders before the
# full-org distro. To flip to FULL (Slack + both contact groups), change MODE
# below to `--send` (drop --test); that is a deliberate one-line change.
#
# The send RENDERS OUR OWN fill — the 'Copy of Org Overrides Ongoing Report'
# (sandbox) tab that override_bulletin.run fills from the real sources. It does
# NOT read the VA's live tab: that tab is a REFERENCE for comparison, not a data
# source (Megan 2026-07-25 — rendering hers would just re-publish her work and
# defeat the automation). It is gated: send.py refuses a week that isn't filled,
# and records the week it sent so the q25m retries never double-email. So if the
# copy tab isn't filled yet, this holds quietly until the fill agent populates it.
#
# launchd fires passes Friday 10:30-13:00 CST (after the ~10am fill window), q25m.
# TIME KNOB: edit StartCalendarInterval in the plist.
#
# Manual dry run (no email):  bash deploy/override_bulletin_send_fri.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.override_bulletin.send" > /dev/null 2>&1; then
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

# SOFT LAUNCH: render OUR copy-tab fill and email the 4-person test group, no
# Slack. `--dry` previews without sending. To go full-org, drop --test (-> --send).
# An ARRAY, because the tab name has spaces — an unquoted string would word-split.
ARGS=(--tab "Copy of Org Overrides Ongoing Report" --test --send)
[ "${1:-}" = "--dry" ] && ARGS=(--tab "Copy of Org Overrides Ongoing Report" --test)

LOG_FILE="$LOG_DIR/override-bulletin-send-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] override-bulletin-send starting (mode: ${ARGS[*]})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.send "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] override-bulletin-send finished exit=$ST" >> "$LOG_FILE"
# A "week not filled" / "already sent" outcome exits 0 — a correct hold, not a
# failure; the next scheduled pass simply tries again.
exit $ST
