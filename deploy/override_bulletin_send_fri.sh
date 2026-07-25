#!/bin/bash
# Override Bulletin — weekly Friday SEND, on the mini (Lucy 1).
#
# SOFT LAUNCH (Megan 2026-07-25): this runs `send --test --send` — it emails the
# rendered bulletin to the 4-person TEST_TO group (Megan, Eve, Carlos, Raf) and
# posts NOTHING to Slack. It is a full week of preview to the leaders before the
# full-org distro. To flip to FULL (Slack + both contact groups), change MODE
# below to `--send` (drop --test); that is a deliberate one-line change.
#
# The send RENDERS the live 'Org Overrides Ongoing Report' tab. It is gated:
# send.py refuses a week that isn't filled, and records the week it sent so the
# q25m retries never double-email. So if the tab isn't filled yet, this holds
# quietly and the next pass tries again.
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

# SOFT LAUNCH: email the 4-person test group, no Slack. `--dry` previews without
# sending. To go full-org, change to MODE="--send".
MODE="--test --send"
[ "${1:-}" = "--dry" ] && MODE="--test"

LOG_FILE="$LOG_DIR/override-bulletin-send-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] override-bulletin-send starting (mode: $MODE)" > "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.send $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] override-bulletin-send finished exit=$ST" >> "$LOG_FILE"
# A "week not filled" / "already sent" outcome exits 0 — a correct hold, not a
# failure; the next scheduled pass simply tries again.
exit $ST
