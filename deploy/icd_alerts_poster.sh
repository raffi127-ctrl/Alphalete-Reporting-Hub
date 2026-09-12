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

# PULL ONCE A DAY, on the first tick inside the window.
#
# This machine ran a whole afternoon on code that had been fixed and pushed
# hours earlier (2026-09-12): the fix existed, the runner did not have it, and
# the only thing that moved it across was somebody remembering to type
# `lucy update --machine "Lucy 3"`. A report nobody has to remember to deploy
# is the whole point of this thing being on a schedule.
#
# ONCE A DAY, NOT EVERY TICK. This wrapper fires every two minutes; pulling
# that often would be pointless traffic and would keep swapping code under a
# run that is already going. The first tick of the day is the quiet moment --
# offices are not selling yet at 08:00.
#
# Same flags and same best-effort stance as deploy/day_orchestrator.sh, which
# has pulled before every batch for months: --ff-only never merges and never
# forces, --autostash parks local edits and puts them back, and a failure is
# swallowed so a network blip can never stop an office's alerts.
PULL_STAMP="$LOG_DIR/.pulled-$(date +%Y-%m-%d)"
if [ -d .git ] && [ ! -f "$PULL_STAMP" ]; then
  touch "$PULL_STAMP"          # BEFORE the pull: a hanging fetch must not
                               # make every later tick retry it.
  git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

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

# The knocks boards, on the same tick but as a SEPARATE run. Their cadence is
# per destination and decided inside knocks_post, so this only has to ask
# often enough; and a credit-check failure must not cost an office its board,
# nor the reverse. --watch belongs only to the alerts leg, so it is dropped.
KNOCK_ARGS=""
case " $* " in *" --send "*) KNOCK_ARGS="--send" ;; esac
"$VENV_PY" -m automations.icd_alerts.knocks_post $KNOCK_ARGS >> "$LOG_FILE" 2>&1
rk=$?
[ "$rc" -eq 0 ] && rc=$rk

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
