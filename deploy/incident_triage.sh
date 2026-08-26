#!/bin/bash
# 8:15am daily — sort the OPEN incidents in #claudecorrections-and-requests into
# "needs a person", "Lucy is retrying it" and "waiting on a source", and put the
# one matching reaction on each post. launchd: com.alphalete.incident-triage.
#
# WHY 8:15: after the 4am flow's main passes and the 7:30 checkpoint email, and
# well before the noon backstop. Triaging mid-flow would grade reports the
# orchestrator is still actively retrying.
#
# WHAT IT CAN TOUCH: reactions on incident posts, plus one line in a thread when
# an incident CHANGES state. Nothing else. It never re-runs a report, never edits
# code, never posts to any other channel. A bad fire costs one wrong emoji.
#
# It refuses to run as anyone but Lucy: Slack only lets you remove your OWN
# reaction, so a circle added under a person's token could never come off again.
#
# Manual dry run (prints the verdicts, touches nothing):
#   bash deploy/incident_triage.sh /dry
#
# CADENCE: the plist's StartCalendarInterval. TIME KNOB is there, not here.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

PY=""
for _cand in .venv/bin/python .venv/bin/python3 python3; do
    if command -v "$_cand" >/dev/null 2>&1 || [ -x "$_cand" ]; then
        if "$_cand" -c "import slack_sdk" >/dev/null 2>&1; then PY="$_cand"; break; fi
    fi
done
if [ -z "$PY" ]; then
    echo "[$(date)] no python with slack_sdk - cannot triage" \
        >> output/logs/incident-triage.skip.log
    exit 1
fi

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

ARGS=""
if [ "${1:-}" = "/dry" ]; then ARGS="--dry-run"; fi

LOG_FILE="output/logs/incident-triage-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] incident triage starting" > "$LOG_FILE"
"$PY" -u -m automations.shared.incident_triage $ARGS >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] incident triage finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub so the card shows it ran (standing rule: a LaunchAgent
# report publishes, or nothing can tell it has stopped firing). Best effort, and
# it can never change the exit code.
if [ -z "$ARGS" ]; then
    "$PY" - "$ST" <<'PYEOF' >> "$LOG_FILE" 2>&1 || true
import sys
from automations.day_orchestrator import hub_publish
hub_publish.publish_done("incident_triage", "Corrections triage",
                         "success" if sys.argv[1] == "0" else "failed")
PYEOF
fi

exit $ST
