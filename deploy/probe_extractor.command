#!/bin/bash
# DIAGNOSTIC (run on Lucy 2): click the robot and dump what appears, so we can
# fix the "Start not found" issue. Sends NOTHING. Copy the output back.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo"; exit 1; }
PY=""
for cand in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.9; do
  if [ -x "$REPO/$cand" ]; then PY="$REPO/$cand"; break; fi
done
if [ -z "$PY" ]; then echo "ERROR: no .venv python under $REPO/.venv/bin"; read -r -p "Return to close…" _; exit 1; fi
export PYTHONPATH="$REPO"; export NO_COLOR=1; export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
echo "Running extractor diagnostic (nobody is sent to AI)…"
echo "A Chrome window opens, logs in, and clicks the robot. Then copy ALL text below."
echo "---------------------------------------------------------------"
"$PY" -u -m automations.resume_pushing._diagnose 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|NotOpenSSLWarning|eol_message"
echo
echo "=== DIAGNOSTIC DONE — copy everything above and send it back ==="
read -r -p "Press Return to close this window…" _
