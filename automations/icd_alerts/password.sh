#!/bin/bash
# Change the SaraPlus password Lucy uses on this computer.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/password.sh | bash
#
# SARAPLUS ROTATES PASSWORDS OFTEN, so this is the command an owner runs on
# their own months after setup -- not a support call, and not a reinstall. It
# asks in a pop-up box and then actually signs in to check, because "saved" on
# a password that does not work leaves them exactly as quiet as before while
# believing it is fixed.
#
# Nothing else is touched: their OwnerVille login, their channels and the
# schedule are all left alone.
set -u

APP="$HOME/.lucy-reports/app"
PY="$HOME/.lucy-reports/venv/bin/python"

if [ ! -x "$PY" ] || [ ! -d "$APP" ]; then
  echo "Lucy Reports is not installed on this computer."
  echo "Ask the reporting team for your setup link."
  exit 1
fi

cd "$APP" || exit 1
echo "Look for the pop-up box..."
exec "$PY" -m automations.icd_alerts.run --set-login
