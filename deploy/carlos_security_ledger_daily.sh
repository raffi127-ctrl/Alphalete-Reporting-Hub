#!/bin/zsh
# Carlos's P&L sheet — daily Tableau Security ledger + captain bonus + balances. Runs from ~/recruiting-report (NOT ~/Desktop: macOS blocks scheduled jobs from Desktop).
cd "$HOME/recruiting-report" || exit 1
mkdir -p output/logs
exec .venv/bin/python -m automations.carlos_security_ledger.run >> output/logs/carlos_security_ledger_daily.log 2>&1
