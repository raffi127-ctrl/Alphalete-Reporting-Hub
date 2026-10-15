#!/bin/bash
# Raf's Daily Update (office 11280) -> 5:00pm CT Mon-Sat on LUCY 2.
# TEST PHASE (Raf, 2026-10-14): writes "Daily Update 2026 - LUCY" and posts
# the Daily Update thread in #org-indeed-accounts. See the module docstring.
# Standalone because Lucy 2's card scheduler runs observe-only — on 10/14 it
# logged "WOULD run raf_daily_update [dry-run]" and nothing ran.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.raf_daily_update.run" > /dev/null 2>&1; then
    echo "[$(date)] raf-daily-update SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/raf-daily-update-$(date +%Y-%m-%d-%H%M%S).log"
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('raf_daily_update','Raf Daily Update')" >> "$LOG_FILE" 2>&1 || true
"$VENV_PY" -u -m automations.raf_daily_update.run --write --test-sheet --post --channel C0BH637AM8F >> "$LOG_FILE" 2>&1
ST=$?
if [ $ST -eq 0 ]; then _PUB=done; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('raf_daily_update','Raf Daily Update','$_PUB')" >> "$LOG_FILE" 2>&1 || true
if [ $ST -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(":rotating_light: *Raf Daily Update* failed",
                      ["```"] + tail + ["```",
                       'Re-run: `lucy rerun raf_daily_update --machine "Lucy 2"`'],
                      tag="raf_daily_update-failed", cfg=load_config(),
                      incident="standalone-raf_daily_update")
except Exception as e:
    print("alert failed:", e)
PY
fi
exit $ST
