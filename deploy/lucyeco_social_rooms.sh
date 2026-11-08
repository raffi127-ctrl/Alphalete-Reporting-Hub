#!/bin/bash
# LucyECO Social rooms tick: makes the private Slack room for any office whose
# LucyECO Social sign-up said "No, please create one for me"
# (#<company-name>-lucyeco-social; Megan, Eve, the ICD, Lucy, the Lucy app and
# @hubposter invited; the Channel ID written back onto the sign-up row).
# Runs on Lucy 3 via launchd (com.alphalete.lucyeco-social-rooms) every 10
# minutes, 7am-9pm only. A quiet no-op when nobody is waiting for a room.
#
#   bash deploy/lucyeco_social_rooms.sh --dry-run   # says what it would make
#   bash deploy/lucyeco_social_rooms.sh             # LIVE, the default
#
# Needs on the machine: Lucy's Slack user token (groups:write to make private
# channels) + the Sheets login that reads the relay workbook.
set -u
cd "$(dirname "$0")/.." || exit 1

# Daytime only: a room made at 2am helps nobody, and 3-5am is the fleet's quiet window.
HOUR=$((10#$(date +%H)))
if [ "$HOUR" -lt 7 ] || [ "$HOUR" -ge 22 ]; then
    exit 0
fi

LIVE="--live"
case " $* " in *" --dry-run "*) LIVE="" ;; esac

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/lucyeco-social-rooms-$(date +%Y-%m-%d).log"
"$VENV_PY" -u -m automations.online_presence.rooms $LIVE >> "$LOG_FILE" 2>&1
ST=$?
[ $ST -ne 0 ] && echo "[$(date)] lucyeco social rooms exit=$ST" >> "$LOG_FILE"
exit $ST
