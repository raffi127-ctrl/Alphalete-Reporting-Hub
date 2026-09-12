#!/bin/bash
# Update Lucy Reports on this computer, in place.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/update.sh | bash
#
# WHY THIS EXISTS. Everything an ICD's laptop DOES lives on that laptop, so
# every change used to mean sending a new zip and talking them through the
# installer again -- three times in one day for the first two offices
# (2026-09-12). That does not survive fifty.
#
# It replaces the program files and NOTHING else: logins, settings and the
# schedule live in ~/.config/lucy-reports and ~/Library/LaunchAgents and are
# never touched. Nothing to re-enter, nothing to re-approve. The next
# scheduled run picks up the new code on its own.
#
# THE FILE LIST IS FETCHED, NOT BAKED IN. It used to be a list inside this
# script, and the moment a new module was added to the agent and not to the
# list, the update ran, said "up to date", and left the machine without it --
# a successful-looking no-op. Worse, GitHub's CDN serves this script from
# cache for a few minutes, so even fixing the list left a window where the old
# one was still being handed out. Now the list is its own file and every fetch
# carries a cache-buster, so a stale script still installs the right files.
set -u

APP="$HOME/.lucy-reports/app"
RAW="https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main"
BUST="$(date +%s)"

if [ ! -d "$APP" ]; then
  echo "Lucy Reports is not installed on this computer (no $APP)."
  echo "Run the installer instead."
  exit 1
fi

cd "$APP" || exit 1
echo "Updating Lucy Reports..."

LIST="$(curl -fsSL "$RAW/automations/icd_alerts/agent_files.txt?t=$BUST")" || {
  echo "Could not reach the update server. Nothing was changed."
  exit 1
}

fail=0
count=0
while IFS= read -r f; do
  case "$f" in ''|'#'*) continue ;; esac
  mkdir -p "$(dirname "$f")"
  # To a temp file first: a half-downloaded module would leave the agent
  # unable to start at all, which is worse than running yesterday's code.
  if curl -fsSL "$RAW/$f?t=$BUST" -o "$f.new"; then
    mv "$f.new" "$f"
    count=$((count + 1))
  else
    rm -f "$f.new"
    echo "  could not fetch $f"
    fail=1
  fi
done <<< "$LIST"

if [ "$fail" -ne 0 ] || [ "$count" -eq 0 ]; then
  echo ""
  echo "Some files did not download — nothing was half-replaced, and Lucy is"
  echo "still running the version she had. Try again on a normal wifi network."
  exit 1
fi

# Prove it still starts. A syntax error in a file we just replaced would
# otherwise show up as silence at the next tick.
if "$HOME/.lucy-reports/venv/bin/python" -c "import automations.icd_alerts.run" 2>/dev/null; then
  echo ""
  echo "Lucy Reports is up to date ($count files). Nothing else to do —"
  echo "your logins and settings are unchanged."
else
  echo ""
  echo "The update downloaded but Lucy could not start with it."
  echo "Please tell the reporting team — your old settings are untouched."
  exit 1
fi
