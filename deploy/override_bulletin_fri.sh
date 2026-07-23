#!/bin/bash
# Override Bulletin — weekly Friday FILL, on the mini (Lucy 1 = Raf's org logins).
# launchd fires passes 09:00-12:55 CST every Friday, q25m. The run resolves which
# week to fill from the ORG Override Summary itself and holds (exit 75) until that
# source has published the new week; once it fills, later passes no-op.
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

# Writes the SANDBOX tab by default. --force because that tab is dirty from build
# testing, so the "already filled" gate would otherwise hold on stale test values.
# Pass "--dry" to this wrapper to preview without writing.
MODE="--write --force"
[ "${1:-}" = "--dry" ] && MODE="--force"

LOG_FILE="$LOG_DIR/override-bulletin-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] override-bulletin starting (mode: $MODE)" > "$LOG_FILE"

"$VENV_PY" -u -m automations.override_bulletin.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 75 = held (the Override Summary hasn't published the week yet) — expected;
# the next pass retries.
echo "[$(date)] override-bulletin finished exit=$ST" >> "$LOG_FILE"
exit 0
