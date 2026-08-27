#!/bin/bash
# Monday 8:00am machine-local (Lucy 1 is Central) — email this week's new
# starts their Slack + Skool join links.
# launchd: com.alphalete.slack-skool-email.
#
# THIS SENDS REAL EMAIL to real people and there is no unsend. Everything that
# could go wrong quietly is refused inside run.py rather than here: a missing,
# wrong-service or stale link, a token that isn't reception's, an empty cohort,
# and a send that already went out today.
#
# Manual: bash deploy/slack_skool_email.sh --dry-run
#
# CADENCE: the plist's StartCalendarInterval. TIME KNOB is there, not here.
set -u
cd "$(dirname "$0")/.." || exit 1

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# No browser in this report, so any venv python with the Google libs will do.
VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import googleapiclient" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with googleapiclient — cannot send" \
        >> "$LOG_DIR/slack-skool-email.skip.log"
    exit 1
fi

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Two concurrent fires would mail the cohort twice. run.py's Sent-mail check
# also catches this, but only after the first has actually landed.
if pgrep -f "automations.slack_skool_email.run" > /dev/null 2>&1; then
    echo "[$(date)] slack_skool_email already running — skipping this fire" \
        >> "$LOG_DIR/slack-skool-email.skip.log"
    exit 0
fi

# --dry-run anywhere in the args wins; otherwise this is the live send.
# --slack rides with --send: the scheduled run is exactly the case where nobody
# is watching a terminal, so the channel is how anyone finds out it went.
MODE="--send --slack"
case " $* " in *" --dry-run "*) MODE="" ;; esac

LOG_FILE="$LOG_DIR/slack-skool-email-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Slack/Skool email starting (mode: ${MODE:-dry-run}, extra args: ${*:-none})" > "$LOG_FILE"

if [ -n "$MODE" ]; then
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('slack_skool_email','Slack / Skool Email')" >> "$LOG_FILE" 2>&1 || true
fi

"$VENV_PY" -u -m automations.slack_skool_email.run $MODE "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Slack/Skool email finished exit=$ST" >> "$LOG_FILE"

# Publish either way, so a refused run shows on the Hub instead of leaving the
# card grey. [[feedback_launchd_reports_must_publish]]
if [ -n "$MODE" ]; then
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('slack_skool_email','Slack / Skool Email','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi

exit 0
