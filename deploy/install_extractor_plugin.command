#!/bin/bash
# ONE-TIME SETUP (run on Lucy 2): install the ApplicantStream AI resume-extractor
# plugin into the resume-pushing automation's OWN Chrome profile.
#
# Why this exists: the scheduled pusher runs in a dedicated, isolated Chrome
# profile (uploaded/.appstream_profile) — NOT your everyday Chrome. An internal
# ApplicantStream plugin can only be installed by a human clicking "Add", and it
# has to be installed into THAT profile so the unattended runs can use it. This
# helper opens Chrome on exactly that profile so your one install click sticks.
#
# HOW TO USE:
#   Double-click this file in Finder (or run it in Terminal) on Lucy 2.
#   A Chrome window opens on the automation profile. Then:
#     1. Log into ApplicantStream if prompted (the rcaptain account).
#     2. Explore Appstream AI -> Applicants -> Process Emails -> Process in Batches.
#     3. Top-right (just above the "Ready For Extraction" area) click the option
#        to INSTALL / DOWNLOAD the AI resume-extractor plugin, and approve
#        Chrome's "Add extension / grant permissions" prompt.
#     4. Click the robot / Resume Helper and confirm it now shows "Start"
#        (an install prompt = not installed yet; a Start button = done).
#     5. Quit Chrome.
#   The plugin now lives in the automation profile and persists for every run.
#
# NOTE: if Chrome says the profile is "already in use", the scheduled pusher is
# mid-run (it runs every 10 min and finishes in a couple minutes) — just wait a
# moment and double-click this again.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="$REPO/uploaded/.appstream_profile"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$PROFILE"
if [ ! -x "$CHROME" ]; then
  echo "ERROR: Google Chrome not found at:"
  echo "  $CHROME"
  echo "Install Google Chrome, then run this again."
  echo
  read -r -p "Press Return to close…" _
  exit 1
fi

echo "==============================================================="
echo " Resume-Pushing — install the AI extractor plugin (one-time)"
echo "==============================================================="
echo "Opening Chrome on the pusher's automation profile:"
echo "  $PROFILE"
echo
echo "In the Chrome window that opens:"
echo "  1) Log into ApplicantStream (rcaptain) if prompted."
echo "  2) Explore Appstream AI -> Applicants -> Process Emails -> Process in Batches."
echo "  3) Top-right, INSTALL the AI resume-extractor plugin + approve the prompt."
echo "  4) Open the robot / Resume Helper; confirm it shows 'Start'."
echo "  5) Quit Chrome."
echo
echo "(If it says the profile is in use, wait ~1 min and run this again.)"
echo "==============================================================="

"$CHROME" --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  "https://applicantstream.com/" >/dev/null 2>&1 &

echo
echo "Chrome launched (PID $!). You can close this Terminal window."
