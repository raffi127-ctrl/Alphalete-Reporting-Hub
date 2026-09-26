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
# LUCY 1 IS THE HOME since 2026-09-22. It started on Lucy 3 -- this needs
# Sheets and Slack, no browser, and Lucy 3 is idle after ~08:30 -- but the
# poster also TEXTS boards and standings to iMessage groups, and texts sent
# from Lucy 3 reached SOME phones and not others (Colten and two of his reps
# saw nothing all afternoon while the same messages from Lucy 1 reached
# everyone). Lucy 1 is the fleet's iMessage box, so it moved. The box needs
# BOTH: Lucy Reporting's Slack user token -- confirm with
# `lucy rerun slack_whoami --machine "Lucy 1"` before arming -- and iMessage
# consent (gap_alerts.config.can_text).
#
# The record of which box runs this is schedule_config.json's
# install_icd_alerts_poster_agent note, not this comment: it was wrong here for
# a day and cost somebody a wrong answer about where a change had to land.
#
# THE HOUR GATE IS HERE as well as in Python, so an off-hours tick costs a few
# milliseconds instead of a Python start-up. It is deliberately WIDER than any
# one office's selling day: offices sit in different timezones, and a laptop
# that wakes late still has a real day to hand over. Posting late is fine;
# never posting is not.

set -u
cd "$(dirname "$0")/.." || exit 1

HOUR=$(date +%H)
HOUR=${HOUR#0}
# NO SUNDAY EXIT. It used to bail here, and that was right when this job only
# posted numbers -- but it now also announces new sign-ups, waiting approvals
# and faults, and none of those keep office hours. An office that signed up on
# a Sunday went unmentioned until Monday morning (caught 2026-09-13, on the
# first sign-up that was meant to prove the announcement worked).
#
# Nothing posts numbers today regardless: in_field_hours is False on Sunday
# for every office, and warn_quiet skips Sunday itself. The gate was belt on
# top of braces, and the belt was catching the wrong things.
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
# `lucy update --machine "<this box>"`. A report nobody has to remember to deploy
# is the whole point of this thing being on a schedule.
#
# ONCE A DAY, NOT EVERY TICK. This wrapper fires every minute; pulling that
# often would be pointless traffic and would keep swapping code under a run
# that is already going. The first tick of the day is the quiet moment --
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

# WHERE THIS TICK STARTS in the day's log. The publish decision below greps
# only what THIS tick wrote: grepping the whole file meant that after the
# day's first alert every later tick matched and published (2026-09-14).
START_BYTES=0
[ -f "$LOG_FILE" ] && START_BYTES=$(wc -c < "$LOG_FILE")

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
# LUCY'S HOURLY CALL-OUTS (Carlos 2026-09-26): reps 15+ min off the doors with
# no fresh credit check, once an hour per opted-in office. Decides its own
# hour inside; a quiet hour says nothing.
"$VENV_PY" -m automations.icd_alerts.gap_callouts $KNOCK_ARGS >> "$LOG_FILE" 2>&1
rk=$?
[ "$rc" -eq 0 ] && rc=$rk

echo "[$(date)] poster done (exit $rc)" >> "$LOG_FILE"

# Report to the Hub so the card's pill reflects a REAL run -- the orchestrator
# never sees a standalone LaunchAgent, and without this a clean run and a
# silent miss are indistinguishable.
#
# NOT ON EVERY TICK. This fires ~900 times a day and publishing each one would
# bury Hub Activity in rows saying "nothing happened", which is how the one row
# that matters stops being visible. Publish when the run actually DID something
# (posted an alert, or warned that an office went quiet) and whenever it
# failed. A preview never publishes: marking the card as ran is what a preview
# must not do.
#
# A CLEAN TICK RIGHT AFTER A FAILED ONE ALWAYS PUBLISHES, even if it posted
# nothing: that tick is the news that it is fixed, and without it the ticket
# the failure opened waits for the next alert to happen (FAIL_STAMP).
#
# THE MANIFEST IS THE DELIVERY PROOF. hub_publish only closes a ticket when
# delivery_check can see one, and this report has no `verify` -- so a clean
# tick with no manifest left failure-icd_alerts_poster open all evening
# (2026-09-14). Written BEFORE publish_done, because that is where the close is
# decided. alert=False on the failed one: publish_done already alerts.
FAIL_STAMP="$LOG_DIR/.icd-alerts-poster-failed"
case " $* " in
  *" --send "*)
    if [ "$rc" -ne 0 ]; then
      _PUB=failed
    elif tail -c +$((START_BYTES + 1)) "$LOG_FILE" 2>/dev/null | grep -q "credit check line(s) ->\|^QUIET:"; then
      _PUB=success
    elif [ -f "$FAIL_STAMP" ]; then
      _PUB=success
    else
      _PUB=""
    fi
    if [ "$_PUB" = "failed" ]; then
      touch "$FAIL_STAMP"
      "$VENV_PY" -c "from automations.shared.run_manifest import write_manifest; write_manifest('icd_alerts_poster', failed=['poster tick exit $rc'], alert=False)" >> "$LOG_FILE" 2>&1 || true
    elif [ "$_PUB" = "success" ]; then
      "$VENV_PY" -c "from automations.shared.run_manifest import write_manifest; write_manifest('icd_alerts_poster', note='poster tick exit 0', alert=False)" >> "$LOG_FILE" 2>&1 || true
    fi
    if [ -n "$_PUB" ]; then
      "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('icd_alerts_poster','ICD Credit-Check Alerts','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    fi
    [ "$_PUB" = "success" ] && rm -f "$FAIL_STAMP"
    ;;
esac

exit $rc
