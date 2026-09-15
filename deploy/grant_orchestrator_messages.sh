#!/bin/bash
# ONE MINUTE AT THE MACHINE. Run this on Lucy 3, click Allow, read the verdict.
#
#   bash deploy/grant_orchestrator_messages.sh
#
# WHAT IT IS FOR. macOS grants "control Messages" per executable identity, and
# the grant belongs to the RESPONSIBLE process -- which for anything typed in
# Terminal is Terminal itself, whatever binary you actually ran. That is why
# deploy/text_consent_check.sh succeeded on Lucy 3 on 2026-09-15 and the
# scheduled sends still could not text: it granted Terminal, and the
# orchestrator is a different identity that holds nothing.
#
# So the dialog HAS to be raised by the poller, under launchd, not by you in a
# shell. This queues the probe, then kickstarts the poller so it picks it up
# now rather than whenever it next wakes -- because waiting on a poll interval
# is a poor use of a minute standing at a Mac mini.
#
# There is no command that grants this. `tccutil` has exactly one subcommand,
# `reset`. Apple made automation consent unautomatable on purpose, which is
# why a person has to be here at all.

set -u

REPO="$HOME/recruiting-report"
LABEL="com.alphalete.mini-control"
cd "$REPO" 2>/dev/null || { echo "No repo at $REPO — wrong machine?"; exit 1; }

echo ""
echo "=============================================================="
echo "  Granting the ORCHESTRATOR permission to send iMessage"
echo "=============================================================="
echo ""
echo "  1. Queueing the probe..."
PYTHONPATH=. .venv/bin/python -m automations.day_orchestrator.mini_control \
  --by Megan --enqueue rerun imessage_identity_probe 2>&1 | sed 's/^/     /'

echo ""
echo "  2. Waking the poller so it runs NOW..."
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null \
  && echo "     poller kicked" \
  || echo "     could not kickstart — it will pick it up on its own schedule"

echo ""
echo "  =========================================================="
echo "   WATCH THE SCREEN. A dialog will ask whether something"
echo "   may control Messages."
echo ""
echo "         CLICK  \"Allow\"  —  NOT \"Don't Allow\"."
echo ""
echo "   Don't Allow is remembered, and the dialog never comes"
echo "   back. Recovering from it means running:"
echo "         tccutil reset AppleEvents"
echo "   and starting over."
echo "  =========================================================="
echo ""
echo "  3. Waiting for the result (up to 3 minutes)..."
echo ""

# TWO PHASES, because a FAILED probe row from an earlier attempt is already
# sitting in the queue history. Matching "imessage_identity_probe && not
# queued" would have matched that stale row on the first pass and declared an
# answer before the dialog was even raised. So: wait for OUR row to show up as
# queued, and only then wait for it to stop being queued.
seen_queued=0
for i in $(seq 1 36); do
  out="$(PYTHONPATH=. .venv/bin/python \
        -m automations.day_orchestrator.mini_control --status 2 2>&1)"
  if printf '%s' "$out" | grep -q "queued  rerun imessage_identity_probe"; then
    seen_queued=1
    sleep 5
    continue
  fi
  if [ "$seen_queued" -eq 1 ] \
     && printf '%s' "$out" | grep -q "imessage_identity_probe"; then
    echo "$out" | tail -12
    echo ""
    # The probe exits 0 either way -- it is a diagnostic -- so the VERDICT
    # line is what says whether this worked, not the exit code.
    if printf '%s' "$out" | grep -q "NO control-Messages"; then
      echo "  ✗ STILL NOT GRANTED. Either the dialog was missed, or it was"
      echo "    answered with Don't Allow. Run:  tccutil reset AppleEvents"
      echo "    then run this script again."
    else
      echo "  Check the Admin Staff chat for a line AND a picture."
      echo "  If both are there, tell Claude and Lucy 3 goes live for texts."
    fi
    exit 0
  fi
  sleep 5
done

echo "  Timed out waiting. Read it later with:"
echo "    lucy logtail rerun imessage_identity_probe 40"
