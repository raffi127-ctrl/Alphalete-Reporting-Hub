#!/bin/bash
# LucyECO Social tick: the whole online-presence pass, on Lucy 3 via launchd
# (com.alphalete.lucyeco-social-rooms) every 10 minutes, 7am-9pm only.
#   1. new sign-ups announced in the alerts channel (#alphaletemarketingbrandhealth)
#   2. a private #<company-name>-lucyeco-social room for anyone who asked
#   3. every LIVE office: what its computer answered (posted / disconnected),
#      the daily "pages still connected?" check, review replies, photo posting
# Dry offices are skipped (run those by hand). A quiet pass when nothing's waiting.
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
echo "[$(date)] pass" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.online_presence.run $LIVE >> "$LOG_FILE" 2>&1
ST=$?
[ $ST -ne 0 ] && echo "[$(date)] lucyeco social pass exit=$ST" >> "$LOG_FILE"

# The Hub card ("LucyECO Social"): told about a FAILURE every time, about a
# clean pass once an hour (the first pass of each hour) -- 84 rows a day of
# "fine" would bury the activity sheet. Never on --dry-run.
if [ -n "$LIVE" ]; then
  MIN=$((10#$(date +%M)))
  if [ $ST -ne 0 ] || [ "$MIN" -lt 10 ]; then
    if [ $ST -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('lucyeco_social','LucyECO Social','$_PUB')" >> "$LOG_FILE" 2>&1 || true
  fi
fi
exit $ST
