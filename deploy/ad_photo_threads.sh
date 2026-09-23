#!/bin/bash
# Ad Photo Threads — the nightly post into each office's #indeed-photos-… channel
# (config.OFFICES; only the ones marked live). Ticks every 30 minutes
# (com.alphalete.ad-photo-threads.plist) and posts each office's day ONCE,
# after 4:30 PM in THAT office's zone, Mon–Fri. The clock gate and the "day already
# posted" check live in Python (run.py nightly) and run before any Sheets or
# Slack call, so an idle tick costs nothing. An interval rather than a calendar
# plist: launchd's cached zone has fired calendar jobs +2h on this fleet.
#
# Manual:  bash deploy/ad_photo_threads.sh --nightly               (a tick)
#          bash deploy/ad_photo_threads.sh --nightly --date 2026-09-21  (force a day)
#          bash deploy/ad_photo_threads.sh --nightly --office carlos     (one office)
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick up pushed fixes before running (the pull is per wrapper, not per box).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# One tick at a time: a posting pass downloads/uploads ~60 screenshots and can
# outlast a tick; two passes would race on state.json and double-post.
if pgrep -f "automations.ad_photo_threads.run" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/ad_photo_threads_$(date +%Y%m%d).log"

"$VENV_PY" -m automations.ad_photo_threads.run "$@" >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "[$(date)] ad-photo-threads rc=$rc" >> "$LOG"
fi
exit $rc
