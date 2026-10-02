#!/bin/zsh
# Carlos's P&L sheet — daily Tiller bank feed -> Ledger. Runs from ~/recruiting-report (NOT ~/Desktop: macOS blocks scheduled jobs from Desktop).
cd "$HOME/recruiting-report" || exit 1
mkdir -p output/logs
exec .venv/bin/python -m automations.carlos_finance.tiller_sync >> output/logs/carlos_tiller_sync.log 2>&1
