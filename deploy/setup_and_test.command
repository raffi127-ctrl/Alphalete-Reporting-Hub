#!/bin/bash
# ONE-SHOT (run on Lucy 2): install the extractor plugin, then test it — all in
# one window so nothing gets pasted out of order. Sends NOBODY to the call list.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo"; exit 1; }
PROFILE="$REPO/automations/uploaded/.appstream_profile"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PY=""; for c in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.9; do
  [ -x "$REPO/$c" ] && PY="$REPO/$c" && break; done
[ -z "$PY" ] && { echo "no .venv python found"; read -r -p "Return to close…" _; exit 1; }

echo "=============================================================="
echo " STEP 1 — closing any Chrome on the automation profile…"
pkill -f appstream_profile; sleep 3

echo " STEP 2 — opening Chrome to INSTALL the plugin…"
"$CHROME" --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check \
  "https://applicantstream.com/" >/dev/null 2>&1 &
echo
echo "  >>> In the Chrome window that just opened:"
echo "      1) Log in (rcaptain) if asked"
echo "      2) Explore Appstream AI -> Applicants -> Process Emails -> Process in Batches"
echo "      3) INSTALL the Resume Helper plugin + approve the prompt"
echo "      4) Click the robot; confirm it shows 'Start' (working)"
echo "      5) Leave Chrome as-is and come back to THIS window"
echo
read -r -p "  >>> Once the plugin is installed, press Return here to continue… " _

echo " STEP 3 — closing the install Chrome…"
pkill -f appstream_profile; sleep 3

echo " STEP 4 — caching the plugin + testing (nobody is sent to AI)…"
echo "=============================================================="
export PYTHONPATH="$REPO"; export NO_COLOR=1; export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
"$PY" -u -m automations.resume_pushing._diagnose 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|NotOpenSSLWarning|eol_message"

echo
echo "=== DONE — copy EVERYTHING above and send it back ==="
read -r -p "Press Return to close this window… " _
