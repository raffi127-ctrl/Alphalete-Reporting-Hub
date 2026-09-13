#!/bin/bash
# Take Lucy Reports off this Mac, completely.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/uninstall.sh | bash
#
# WHY THIS EXISTS. Until now there was no way off: revoking an office turned
# its key off on our side while its laptop kept waking up, opening a browser
# and talking to a relay that refused it -- forever, on a machine we do not
# own. "Nothing to uninstall" was true of our DATA and never true of their
# computer.
#
# It is also what makes the flow SAFE TO TEST. Megan has to be able to run the
# whole thing on her own Mac and put it back exactly as it was.
#
# IT DELETES THEIR SARAPLUS AND OWNERVILLE LOGINS TOO, which is the point --
# those live only on this machine, so leaving them behind on a computer that
# is finished with the program is the worst of both. It asks first.

set -u

BASE="$HOME/.lucy-reports"
CONFIG="$HOME/.config/lucy-reports"
PLIST="$HOME/Library/LaunchAgents/com.alphalete.lucy-reports.plist"

echo ""
echo "This removes the Lucy Ecosystem from this computer:"
echo ""
[ -f "$PLIST" ]     && echo "  • the schedule that wakes it up"
[ -d "$BASE" ]      && echo "  • the program itself       ($BASE)"
[ -d "$CONFIG" ]    && echo "  • your saved logins        ($CONFIG)"
if [ ! -f "$PLIST" ] && [ ! -d "$BASE" ] && [ ! -d "$CONFIG" ]; then
  echo "  (nothing found — it is not installed on this computer)"
  echo ""
  exit 0
fi
echo ""
echo "Your numbers in Slack are not affected by this, and nothing on"
echo "Alphalete's side is deleted."
echo ""
# READ FROM THE TERMINAL, NOT STDIN. This script is delivered by
# `curl ... | bash`, which makes stdin the PIPE -- so a plain `read` gets EOF
# immediately, takes it as "no", and prints "Nothing was changed" before the
# person has typed anything. Megan hit exactly that on 2026-09-13 and was left
# believing it had been removed when nothing had (she then typed REMOVE at her
# shell prompt, which is what a script that answers its own question looks
# like from the outside).
if [ ! -r /dev/tty ]; then
  echo "This needs to be run somewhere it can ask you a question."
  echo "Open Terminal and paste the command there."
  exit 1
fi
printf "Type REMOVE and press Return to go ahead: "
read -r answer < /dev/tty
if [ "$answer" != "REMOVE" ]; then
  echo ""
  echo "Nothing was changed."
  exit 0
fi

echo ""
# Stop it FIRST. Deleting the program out from under a running tick leaves a
# half-finished browser process and a launchd job that keeps retrying it.
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  echo "  stopped the schedule"
fi

# Any browser it left open. Matched on the profile path so this can only ever
# reach a Chrome that Lucy Reports itself launched.
pkill -f "$CONFIG/chrome-profile" 2>/dev/null

for d in "$BASE" "$CONFIG"; do
  if [ -d "$d" ]; then
    rm -rf "$d"
    echo "  removed $d"
  fi
done

echo ""
echo "The Lucy Ecosystem is off this computer."
echo ""
echo "If this office is coming back, the setup link you were sent still works."
echo ""
