#!/bin/bash
# Daily EOD AppStream -- Camila's 2nd round retention email, 6 PM CENTRAL
# (20:00 Argentina now, 21:00 after Nov 1), Monday to Saturday, a dia vencido
# (Camila / Eve, 2026-10-07). LIVE: goes to Camila (+ Eve copied).
#
# launchd fires at 16:00-19:00 on this machine's LOCAL clock; the module's
# --scheduled gate lets through only the fire that is 18:00 Central.
#
#   bash deploy/daily_eod_appstream.sh                # the scheduled pass
#   bash deploy/daily_eod_appstream.sh --dry-run      # now, send nothing
#
# Needs the AppStream session, so it runs on the machine that holds it.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/daily-eod-appstream-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] daily-eod-appstream starting (args: $*)" > "$LOG_FILE"

if [ $# -eq 0 ]; then
  "$VENV_PY" -m automations.daily_eod_appstream.run --scheduled --production >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -m automations.daily_eod_appstream.run "$@" >> "$LOG_FILE" 2>&1
fi
ST=$?
echo "[$(date)] daily-eod-appstream finished exit=$ST" >> "$LOG_FILE"
exit $ST
