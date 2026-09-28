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
# The rule it applies is the same one relay.is_desktop() applies: ASK THE
# MACHINE ITS MODEL NAME FIRST ("iMac", "Mac mini", "MacBook Pro" -- what
# system_profiler prints, not the generic "Mac14,7" identifier), and only fall
# back to the battery probe when the name is unrecognised. The battery alone
# turned away Carlos's Mac mini on 2026-09-15 and Max's iMac on 2026-09-28
# ("laptop (it has a battery)"): some desktops report an AppleSmartBattery,
# and a probe that can only answer by absence refuses them at the first step.
# relay.is_desktop() learned this on 9/15; this script had not.

set -u

BOLD=$'\033[1m'; OFF=$'\033[0m'; RED=$'\033[31m'; GREEN=$'\033[32m'
[ -n "${NO_COLOR:-}" ] && { BOLD=""; OFF=""; RED=""; GREEN=""; }

echo ""
echo "${BOLD}Checking this computer...${OFF}"
echo ""

NAME="$(scutil --get ComputerName 2>/dev/null || hostname 2>/dev/null)"
echo "  Computer: ${NAME:-unknown}"

MODEL="$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Model Name/ {print $2; exit}')"
[ -n "${MODEL:-}" ] && echo "  Model:    ${MODEL}"
LAPTOP=""
case "$(printf '%s' "${MODEL:-}" | tr '[:upper:]' '[:lower:]')" in
  macbook*)                                   LAPTOP="yes" ;;   # laptop, definitively
  *"mac mini"*|*imac*|*"mac studio"*|*"mac pro"*) LAPTOP="no" ;; # desktop, definitively
  *)
    # Unrecognised model: the battery still catches the common case.
    if ioreg -rc AppleSmartBattery 2>/dev/null | grep -q AppleSmartBattery; then
      LAPTOP="yes"
    else
      LAPTOP="no"
    fi ;;
esac

if [ "$LAPTOP" = "yes" ]; then
  echo "  Type:     laptop"
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

echo "  Type:     desktop"
echo ""
echo "  ${BOLD}${GREEN}This computer can be used.${OFF}"
echo ""
echo "  Nothing has been installed. Go back to your setup page and run the"
echo "  install line when you are ready."
echo ""
