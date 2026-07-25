#!/bin/bash
# Intraday BOTH-MACHINE error watcher — runs ON LUCY 1 every ~30 min all day.
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

# Only sweep during the active report window (04–21 CST) — the mini is Central, so
# no wasted Sheet reads overnight. launchd fires this every 30 min; this gate makes
# the off-hours firings a no-op.
HOUR=$(date +%H)
if [ "$HOUR" -lt 4 ] || [ "$HOUR" -ge 21 ]; then
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

"$VENV_PY" -m automations.machine_digest.run --watch \
  --host "Mac.attlocal.net,Carloss-Mac-mini-2" "$@" >> "$LOG_FILE" 2>&1
ST=$?
if [ "$ST" -ne 0 ]; then
  echo "[$(date)] error-watch exit=$ST" >> "$LOG_FILE"
fi
exit 0
