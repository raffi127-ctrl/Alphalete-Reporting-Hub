#!/bin/bash
# OPTION A (run on Lucy 2, once): genuinely install the Resume Helper plugin into
# a FRESH, DEDICATED Chrome profile that the automation's stealth browser NEVER
# touches — so the install can't be stripped. Also log in here so the profile
# carries a session. This is plain Chrome, exactly like where the plugin works.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="$REPO/automations/uploaded/.extract_profile"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$PROFILE"
[ -x "$CHROME" ] || { echo "Google Chrome not found at $CHROME"; read -r -p "Return to close…" _; exit 1; }

# close anything already on this dedicated profile
pkill -f ".extract_profile" 2>/dev/null; sleep 2

echo "=============================================================="
echo " Dedicated extract profile — install the Resume Helper plugin"
echo "=============================================================="
echo "Profile: $PROFILE"
echo
echo "In the Chrome window that opens:"
echo "  1) Log into ApplicantStream (your normal account)"
echo "  2) Explore Appstream AI -> Applicants -> Process Emails -> Process in Batches"
echo "  3) INSTALL the Resume Helper plugin ('Add to Chrome' / Download) + approve"
echo "  4) Click the robot; confirm it shows 'Start' (working)"
echo "  5) Quit Chrome"
echo "=============================================================="

"$CHROME" --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  "https://applicantstream.com/" >/dev/null 2>&1 &
echo
echo "Chrome launched (pid $!). Do the steps above, then quit Chrome."
echo "This Terminal window can be closed."
