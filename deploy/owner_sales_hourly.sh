#!/bin/bash
# Owner Sales Hourly — every owner's sales so far today (Lucy ECO relay),
# texted into the "Alphalete Owners" iMessage chat (Raf 2026-10-24).
# Runs on Lucy 1 (texting machine, alphaletereporting@gmail.com).
#
# TIME KNOB: StartCalendarInterval in com.alphalete.owner-sales-hourly.plist
# (the code also refuses to text outside config.WINDOW).
#
# Manual dry test (prints the text, sends nothing):
#   bash deploy/owner_sales_hourly.sh --force
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.owner_sales_hourly.run" > /dev/null 2>&1; then
    echo "[$(date)] owner-sales-hourly SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/owner-sales-hourly-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] owner-sales-hourly starting: $*" > "$LOG_FILE"

case " $* " in
  *" --send "*) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('owner_sales_hourly','Owner Sales Hourly')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.owner_sales_hourly.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] owner-sales-hourly finished exit=$ST" >> "$LOG_FILE"
case " $* " in
  *" --send "*) if [ "$ST" = "0" ]; then _PUB=success; else _PUB=failed; fi
     "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('owner_sales_hourly','Owner Sales Hourly','$_PUB')" >> "$LOG_FILE" 2>&1 || true ;;
esac
[ "$ST" = "0" ] && touch "output/logs/.owner-sales-hourly-ran-$(date +%Y-%m-%d)" 2>/dev/null || true
exit 0
