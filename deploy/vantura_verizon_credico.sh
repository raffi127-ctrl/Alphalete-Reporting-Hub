#!/bin/bash
# Vantura 'Verizon Sales Board' <- Credico Sales Verification (LUCY 2, daily
# 11:10am + 12:40pm CT). Credico emails the office's Sales Verification xlsx
# (sales through YESTERDAY) to the Hub inbox ~10:45; this sets each matched
# rep's day cells to Credico's valid lines (the Slack roster fill is the live
# ticker, this is the correction) and writes column Q 'Approved'. Idempotent:
# only changed cells are written; after a write the Verizon day + week boards
# are re-posted '(corrected)' into the day's Verizon Metrics thread. See the
# module docstring.
#   plan only:  .venv/bin/python -m automations.vantura_verizon_credico.run --plan
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.vantura_verizon_credico.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura-verizon-credico SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/vantura-verizon-credico-$(date +%Y-%m-%d-%H%M%S).log"
"$VENV_PY" -u -m automations.vantura_verizon_credico.run --fill --yes --repost >> "$LOG_FILE" 2>&1
ST=$?
if [ $ST -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(":rotating_light: *Vantura Verizon board (Credico) fill* failed",
                      ["```"] + tail + ["```",
                       'Re-run: `lucy rerun vantura_verizon_credico --machine "Lucy 2"`'],
                      tag="vantura_verizon_credico-failed", cfg=load_config(),
                      incident="standalone-vantura_verizon_credico")
except Exception as e:
    print("alert failed:", e)
PY
fi
exit $ST
