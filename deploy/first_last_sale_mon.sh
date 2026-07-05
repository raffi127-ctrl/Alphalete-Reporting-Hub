#!/bin/bash
# Monday 2:00pm CST — First Sale / Last Sale auto-ingest, on the always-on Mac
# mini via launchd (com.alphalete.first-last-sale-mon).
#
# WHY its own 2pm job (not the 4am day-orchestrator): Smart Circle (Campbell,
# cdeliscu@thesmartcircle.com) emails the 'B2B.D2D First Last Sale WE ….xlsx'
# Monday morning — observed ~8:50am–1:11pm CT — and the report auto-fetches it
# via --email. The morning orchestrator's noon backstop can't wait for a ~1pm
# email, so this dedicated job runs it after it reliably lands (2pm ≈ 50min past
# the latest arrival seen). first_last_sale is on_scheduler:false in
# schedule_config.json so it doesn't also try (and fail) in the morning batch.
#
# The run pulls the newest workbook, fills the FK/LK section across the ATT tabs
# (week from the filename), writes its manifest, and publishes 'ran' to the Hub.
# A missing email = a clean no-op (partial-safe). Non-zero exit = a real error.
#
# Manual test without writing:  bash deploy/first_last_sale_mon.sh --dry-run
# (passes through to the module; --dry-run is appended and wins.)
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/first-last-sale-mon-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] First/Last Sale auto-ingest starting (extra args: ${*:-none})" > "$LOG_FILE"

# Default to --email; any extra arg (e.g. --dry-run) is appended and wins.
"$VENV_PY" -u -m automations.first_last_sale.run --email "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] First/Last Sale run finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"First/Last Sale auto-ingest failed (exit $ST) — check the log or the reporting inbox\" with title \"First/Last Sale\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
