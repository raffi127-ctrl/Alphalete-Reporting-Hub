#!/bin/bash
# Intraday BOTH-MACHINE error watcher — runs ON LUCY 1 every ~10 min all day.
# (com.alphalete.lucy2-digest.) The Hub Activity log is shared, so from the mini
# we can see every report's outcome on BOTH Lucy 1 and Lucy 2. It posts a deduped,
# real-time corrections Slack alert for any STANDALONE report (either machine) that
# errored / ran partial today — orchestrator-managed reports already self-alert in
# real time, so the watcher skips them. NO summary email (Megan 2026-07-25: know
# all day which reports errored on both Lucy 1 and Lucy 2). Silent when nothing's
# newly wrong; dedup state is per-day so each problem posts once.
#
#   bash deploy/lucy2_digest_daily.sh --dry-run   # print, don't post
#
# --host is the Lucy-2 hostname list, used only to LABEL a row as Lucy 1 vs Lucy 2
# (tolerant of .local vs .attlocal.net). If Carlos's mini is renamed, update it.

set -u
cd "$(dirname "$0")/.." || exit 1

# Only sweep during the active report window (04:00–23:59 CST) — the mini is
# Central, and the latest scheduled job is STF Field Check at 23:00, so the window
# runs to midnight to catch it. Nothing runs 00:00–03:59, so skip then (no wasted
# Sheet reads overnight). launchd fires this every 10 min; this gate no-ops the
# off-hours firings.
HOUR=$(date +%H)
if [ "$HOUR" -lt 4 ]; then
  exit 0
fi

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/error-watch-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Every hostname Lucy 2 has answered to — the list is match-ANY, so keeping the
# retired names costs nothing and a missing name is silent damage: Lucy 2 moved to
# Lucys-MacBook-Neo.local after 2026-08-06, so from 8/7 every Lucy-2 alert was
# labeled "Lucy 1" and pointed people at the wrong machine (Eve 2026-08-13).
"$VENV_PY" -m automations.machine_digest.run --watch \
  --host "Lucys-MacBook-Neo,Mac.attlocal.net,Carloss-Mac-mini-2" "$@" >> "$LOG_FILE" 2>&1
ST=$?
if [ "$ST" -ne 0 ]; then
  echo "[$(date)] error-watch exit=$ST" >> "$LOG_FILE"
fi
exit 0
