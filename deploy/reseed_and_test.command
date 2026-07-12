#!/bin/bash
# ONE-SHOT (run on Lucy 2): re-seed the ApplicantStream login (clears Cloudflare
# ONCE, by hand), then test the extractor plugin. Sends NOBODY to the call list.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo"; exit 1; }
PY=""; for c in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.9; do
  [ -x "$REPO/$c" ] && PY="$REPO/$c" && break; done
[ -z "$PY" ] && { echo "no .venv python found"; read -r -p "Return to close…" _; exit 1; }
export PYTHONPATH="$REPO"; export NO_COLOR=1; export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "=============================================================="
echo " STEP 1 — closing any Chrome on the automation profile…"
pkill -f appstream_profile; sleep 3

echo " STEP 2 — RE-SEED THE LOGIN (a browser will open)"
echo "   In that browser window:"
echo "     1) clear the Cloudflare 'verify you are human' check if shown"
echo "     2) make sure you're logged in as rcaptain"
echo "     3) then go to:   applicantstream.com/index.cfm?p=701"
echo "     4) wait — it saves automatically once the office search box appears"
echo "=============================================================="
"$PY" -u -m automations.shared.tableau_patchright --appstream-login 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|NotOpenSSLWarning|eol_message"

echo
echo " STEP 3 — closing that browser + testing the plugin (nobody sent to AI)…"
pkill -f appstream_profile; sleep 3
"$PY" -u -m automations.resume_pushing._diagnose 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|NotOpenSSLWarning|eol_message"

echo
echo "=== DONE — copy EVERYTHING above and send it back ==="
read -r -p "Press Return to close this window… " _
