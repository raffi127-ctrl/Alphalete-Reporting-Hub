#!/bin/bash
# ICD credit-check alerts — read what the offices' laptops relayed and post it.
#
#   bash deploy/icd_alerts_poster.sh                 # PREVIEW, posts nothing
#   bash deploy/icd_alerts_poster.sh --send --watch  # what launchd runs
#
# RUNS ON A LUCY, and specifically one holding Lucy Reporting's Slack user
# token. The token is per MACHINE: from Megan's laptop the same command posts
# every alert under HER name into an ICD's channel. post.py refuses to --send
# unless auth_test() says Lucy Reporting, so a wrong box fails loudly instead
# of quietly doing the wrong thing.
#
# Lucy 3 is the right home on load -- this needs Sheets and Slack, no browser,
# no iMessage, and Lucy 3 is idle after ~08:30. Confirm it has the user token
# before arming: `lucy rerun slack_whoami --machine "Lucy 3"`.
#
# THE HOUR GATE IS HERE as well as in Python, so an off-hours tick costs a few
# milliseconds instead of a Python start-up. It is deliberately WIDER than any
# one office's selling day: offices sit in different timezones, and a laptop
# that wakes late still has a real day to hand over. Posting late is fine;
# never posting is not.

set -u
cd "$(dirname "$0")/.." || exit 1

DOW=$(date +%u)     # 1=Mon .. 7=Sun
HOUR=$(date +%H)
HOUR=${HOUR#0}
[ "$DOW" = "7" ] && exit 0                  # no office relays on Sunday
[ "$HOUR" -lt 8 ] && exit 0
[ "$HOUR" -gt 23 ] && exit 0

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/icd-alerts-poster-$(date +%Y-%m-%d).log"

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] poster starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.icd_alerts.post "$@" >> "$LOG_FILE" 2>&1
# GRAB $? FIRST. A $(date) in the same echo runs before $? is expanded and
# command substitution RESETS it, so this would log the status of `date`
# (always 0) and a crashed run would read green.
rc=$?
echo "[$(date)] poster done (exit $rc)" >> "$LOG_FILE"

# Report to the Hub so the card's pill reflects a REAL run -- the orchestrator
# never sees a standalone LaunchAgent, and without this a clean run and a
# silent miss are indistinguishable.
#
# NOT ON EVERY TICK. This fires ~90 times a day and publishing each one would
# bury Hub Activity in rows saying "nothing happened", which is how the one row
# that matters stops being visible. Publish when the run actually DID something
# (posted an alert, or warned that an office went quiet) and whenever it
# failed. A preview never publishes: marking the card as ran is what a preview
# must not do.
case " $* " in
  *" --send "*)
    if [ "$rc" -ne 0 ]; then
      _PUB=failed
    elif grep -q "credit check line(s) ->\|^QUIET:" "$LOG_FILE" 2>/dev/null; then
      _PUB=success
    else
      _PUB=""
    fi
    if [ -n "$_PUB" ]; then
      "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('icd_alerts_poster','ICD Credit-Check Alerts','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    fi
    ;;
esac

exit $rc
