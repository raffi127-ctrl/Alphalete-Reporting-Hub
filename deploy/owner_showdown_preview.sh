#!/bin/bash
# August Owner Showdown — 8:00am PREVIEW to Megan only (Megan 2026-08-03:
# "email it to me first around 8am and then I can correct if needed").
#
# Runs the same pull the 9:00am send will run, renders the same flyer, and emails
# it to MEGAN ALONE with a list of what moved since the sheet's current numbers.
# --preview forces a dry run, so this pass writes NOTHING to the KTS tab; the
# 9:00am agent does the real fill and the real send to all 48.
#
# That gives an hour to stop it:  lucy rerun disable_owner_showdown_agent
#
# Manual test:  bash deploy/owner_showdown_preview.sh
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.owner_showdown.run" > /dev/null 2>&1; then
    echo "[$(date)] owner-showdown-preview SKIPPED — a run is already going"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
# Deliberately NOT setting OWNER_SHOWDOWN_AGENT: the preview writes nothing and
# must not publish a Hub run row — that belongs to the 9am pass.

LOG_FILE="$LOG_DIR/owner-showdown-preview-$(date +%Y-%m-%d-%H%M%S).log"
MARKER="$LOG_DIR/.owner-showdown-preview-$(date +%Y-%m-%d)"

if [ -f "$MARKER" ]; then
    echo "[$(date)] preview already sent today — skipping" >> "$LOG_FILE"
    exit 0
fi

echo "[$(date)] owner-showdown preview starting (Megan only, no writes)" \
    > "$LOG_FILE"
"$VENV_PY" -u -m automations.owner_showdown.run --preview >> "$LOG_FILE" 2>&1
ST=$?

if [ "$ST" -eq 0 ]; then
    touch "$MARKER"
    find "$LOG_DIR" -name ".owner-showdown-preview-*" -mtime +3 -delete 2>/dev/null
    echo "[$(date)] preview emailed" >> "$LOG_FILE"
else
    echo "[$(date)] preview FAILED (exit $ST) — the 9am send is NOT blocked by" \
         "this; stop it by hand if the numbers are in doubt" >> "$LOG_FILE"
fi
echo "[$(date)] owner-showdown preview finished exit=$ST" >> "$LOG_FILE"
exit $ST
