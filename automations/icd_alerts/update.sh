#!/bin/bash
# Update Lucy Reports on this computer, in place.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/update.sh | bash
#
# WHY THIS EXISTS. Everything an ICD's laptop DOES lives on that laptop, so
# every change to it used to mean sending them a new zip and talking them
# through the installer again -- three times in one day for the first two
# offices (2026-09-12). That does not survive fifty.
#
# It replaces the program files and nothing else: the logins, the saved
# settings and the schedule are all untouched, because they live in
# ~/.config/lucy-reports and ~/Library/LaunchAgents. There is nothing to
# re-enter and nothing to approve again.
#
# The next scheduled run picks up the new code on its own -- the agent is
# started fresh each time, so there is no service to restart.
set -u

APP="$HOME/.lucy-reports/app"
RAW="https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main"

if [ ! -d "$APP" ]; then
  echo "Lucy Reports is not installed on this computer (no $APP)."
  echo "Run the installer instead."
  exit 1
fi

FILES=(
  "automations/icd_alerts/__init__.py"
  "automations/icd_alerts/config.py"
  "automations/icd_alerts/relay.py"
  "automations/icd_alerts/sara_read.py"
  "automations/icd_alerts/state.py"
  "automations/icd_alerts/run.py"
  "automations/icd_alerts/ov_read.py"
  "automations/shared/ownerville_knocks.py"
  "automations/shared/saraplus.py"
  "automations/shared/credit_check_line.py"
  "automations/shared/sale_hype.py"
  "automations/shared/browser_banner.py"
)

cd "$APP" || exit 1
echo "Updating Lucy Reports..."
fail=0
for f in "${FILES[@]}"; do
  mkdir -p "$(dirname "$f")"
  # To a temp file first: a half-downloaded module would leave the agent
  # unable to start at all, which is worse than running yesterday's code.
  if curl -fsSL "$RAW/$f" -o "$f.new"; then
    mv "$f.new" "$f"
  else
    rm -f "$f.new"
    echo "  could not fetch $f"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Some files did not download — nothing was half-replaced, and Lucy is"
  echo "still running the version she had. Try again on a normal wifi network."
  exit 1
fi

# Prove it still starts. A syntax error in a file we just replaced would
# otherwise show up as silence at the next tick.
if "$HOME/.lucy-reports/venv/bin/python" -c "import automations.icd_alerts.run" 2>/dev/null; then
  echo ""
  echo "Lucy Reports is up to date. Nothing else to do —"
  echo "your logins and settings are unchanged."
else
  echo ""
  echo "The update downloaded but Lucy could not start with it."
  echo "Please tell the reporting team — your old settings are untouched."
  exit 1
fi
