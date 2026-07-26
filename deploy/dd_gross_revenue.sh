#!/bin/bash
# Pay Structure — ICD gross-revenue pull. Runs ON LUCY 1 on the 1st & 15th at
# noon (com.alphalete.dd-gross-revenue). Pulls each office's base-tier gross
# revenue (Total $ to ICD) + activation from DD DETAIL (ORG) into the
# "Pay Structure Gross Revenue" tab, so the pay-structure gross-profit simulator
# uses real numbers. Low-urgency, off the 4am batch (Raf/Megan 2026-07-25).
#
#   bash deploy/dd_gross_revenue.sh            # pull + write the sheet
#
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dd-gross-revenue-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export PYTHONPATH="$(pwd)"
export PAY_STRUCTURE_SHEET_ID="1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"

echo "[$(date)] dd_gross_revenue start" >> "$LOG_FILE"
"$VENV_PY" -m automations.pay_structure.dd_pull --write >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] dd_gross_revenue exit=$ST" >> "$LOG_FILE"
exit $ST
