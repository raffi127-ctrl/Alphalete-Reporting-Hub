#!/bin/bash
# TEST the resume extractor AFTER installing the plugin (run on Lucy 2, once).
# Runs the EXTRACT step ONLY — it NEVER sends anyone to the AI call list, so it
# is safe to run. It logs in, opens the v2 batch page, and tries the robot /
# Resume Helper. Copy the output at the end and send it back.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo"; exit 1; }

PY=""
for cand in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.9; do
  if [ -x "$REPO/$cand" ]; then PY="$REPO/$cand"; break; fi
done
if [ -z "$PY" ]; then echo "ERROR: no .venv python found under $REPO/.venv/bin"; read -r -p "Return to close…" _; exit 1; fi

export PYTHONPATH="$REPO"
export NO_COLOR=1
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "==============================================================="
echo " Resume-Pushing — EXTRACT-ONLY test (nobody is sent to AI)"
echo "==============================================================="
echo "Using python: $PY"
echo "A Chrome window will open, log in, and try to extract. Watch it,"
echo "then copy ALL the text below and send it back."
echo "---------------------------------------------------------------"
echo

"$PY" -u -m automations.resume_pushing.run --extract-only 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|NotOpenSSLWarning|eol_message"

echo
echo "=== TEST DONE — copy everything above and send it back ==="
read -r -p "Press Return to close this window…" _
