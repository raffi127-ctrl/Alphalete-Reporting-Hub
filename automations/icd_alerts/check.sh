#!/bin/bash
# Is this computer the right one? Installs NOTHING.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/check.sh | bash
#
# WHY THIS EXISTS SEPARATELY from the installer's own check. setup.py refuses
# a laptop before it copies anything, which is correct -- but by then somebody
# has already pasted a line, watched it download, and been turned away. Megan
# 2026-09-13: "there should be a 'run check' button where you can then confirm
# it's a stationary machine before any install happens."
#
# PURE SHELL, no Python and no download of the agent. This has to work on a
# machine that has nothing set up on it yet, which is the whole point -- and a
# check with prerequisites is a check that can fail for reasons that have
# nothing to do with the answer.
#
# The rule it applies is the same one relay.is_desktop() applies: a battery or
# not. Not the model name, because Apple Silicon reports generic strings like
# "Mac14,7" for laptops AND desktops.

set -u

BOLD=$'\033[1m'; OFF=$'\033[0m'; RED=$'\033[31m'; GREEN=$'\033[32m'
[ -n "${NO_COLOR:-}" ] && { BOLD=""; OFF=""; RED=""; GREEN=""; }

echo ""
echo "${BOLD}Checking this computer...${OFF}"
echo ""

NAME="$(scutil --get ComputerName 2>/dev/null || hostname 2>/dev/null)"
echo "  Computer: ${NAME:-unknown}"

if ioreg -rc AppleSmartBattery 2>/dev/null | grep -q AppleSmartBattery; then
  echo "  Type:     laptop (it has a battery)"
  echo ""
  echo "  ${BOLD}${RED}This computer cannot be used.${OFF}"
  echo ""
  echo "  Lucy has to read your numbers all day. A laptop stops the moment"
  echo "  its lid is closed or it goes to sleep, so your channel would go"
  echo "  quiet without anybody noticing."
  echo ""
  echo "  Please run the setup on a desktop that stays on in the office:"
  echo "  an iMac, a Mac mini or a Mac Studio."
  echo ""
  exit 1
fi

echo "  Type:     desktop (no battery)"
echo ""
echo "  ${BOLD}${GREEN}This computer can be used.${OFF}"
echo ""
echo "  Nothing has been installed. Go back to your setup page and run the"
echo "  install line when you are ready."
echo ""
