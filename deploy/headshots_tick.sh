#!/bin/bash
# Headshot processing tick — reads replies to the Monday "Headshot Submissions"
# threads (this week + last week) in #11280-alphalete-marketing-inc-rafael-
# hidalgo, turns each photo+name reply into a white-background headshot, and
# posts it back in the thread as Lucy. State in ~/.config/headshots/ makes
# every reply process exactly once; a reply with no name gets asked ONCE.
# Runs on the always-on Mac mini via launchd (com.alphalete.headshots-tick),
# every 10 minutes. Quiet no-op when there's no thread or nothing new.
#
#   bash deploy/headshots_tick.sh --dry-run   # previews only, posts nothing
#   bash deploy/headshots_tick.sh             # LIVE — the default
#
# Needs on the machine: Lucy Slack user token + `rembg`/`onnxruntime` in the
# venv (lucy pip_install rembg / onnxruntime). First processing run downloads
# the u2net_human_seg model (~170 MB) to ~/.u2net/ once.
set -u
cd "$(dirname "$0")/.." || exit 1

# HELD with the Monday post (Megan 2026-08-23) — no processing until the
# end-to-end flow (incl. OwnerVille upload) is approved. Flip to 1 + push +
# `lucy update` to go live.
HEADSHOTS_LIVE="${HEADSHOTS_LIVE:-0}"
if [ "$HEADSHOTS_LIVE" != "1" ]; then
    exit 0
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/headshots-tick-$(date +%Y-%m-%d).log"
"$VENV_PY" -u -m automations.headshots.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
[ $ST -ne 0 ] && echo "[$(date)] headshots tick exit=$ST" >> "$LOG_FILE"
exit $ST
