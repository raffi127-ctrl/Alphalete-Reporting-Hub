#!/bin/zsh
# Carlos's P&L sheet — Thursday Apex payroll export. Runs from ~/recruiting-report (NOT ~/Desktop: macOS blocks scheduled jobs from Desktop).
cd "$HOME/recruiting-report" || exit 1
mkdir -p output/logs
exec .venv/bin/python -m automations.carlos_payroll_pull.run >> output/logs/carlos_payroll_pull_thu.log 2>&1
