#!/bin/bash
# Owner Knocks Hourly — every org owner's knocks so far today (Lucy ECO relay),
# as one board, texted into the "Alphalete Owners" iMessage chat (Raf 2026-10-29).
# Runs on Lucy 1 (texting machine, alphaletereporting@gmail.com).
#
# TIME KNOB: StartCalendarInterval in com.alphalete.owner-knocks-hourly.plist
# (the code also refuses to text outside config.WINDOW).
#
# Manual dry test (draws the board, sends nothing):
#   bash deploy/owner_knocks_hourly.sh --force
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.owner_knocks_hourly.run" > /dev/null 2>&1; then
    echo "[$(date)] owner-knocks-hourly SKIPPED — previous pass still running"
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
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/owner-knocks-hourly-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] owner-knocks-hourly starting: $*" > "$LOG_FILE"

case " $* " in
  *" --send "*) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('owner_knocks_hourly','Owner Knocks Hourly')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.owner_knocks_hourly.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] owner-knocks-hourly finished exit=$ST" >> "$LOG_FILE"
case " $* " in
  *" --send "*) if [ "$ST" = "0" ]; then _PUB=success; else _PUB=failed; fi
     "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('owner_knocks_hourly','Owner Knocks Hourly','$_PUB')" >> "$LOG_FILE" 2>&1 || true ;;
esac
[ "$ST" = "0" ] && touch "output/logs/.owner-knocks-hourly-ran-$(date +%Y-%m-%d)" 2>/dev/null || true
exit 0
