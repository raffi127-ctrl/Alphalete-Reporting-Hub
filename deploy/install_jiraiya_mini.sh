#!/bin/bash
# Install Jiraiya (the /dd DD bot) + its 3am harvest as always-on LaunchAgents
# ON THIS MACHINE (run it on the mini). Generates path-correct plists from the
# current repo location, so it works regardless of the mini's user/path.
#
# BEFORE running, place the two Jiraiya tokens on this machine (copy each from the
# Slack app, then):
#   mkdir -p ~/.config/recruiting-report
#   pbpaste > ~/.config/recruiting-report/dd-bot-token   # xoxb-… (Bot User OAuth Token)
#   pbpaste > ~/.config/recruiting-report/dd-app-token   # xapp-… (App-Level Token)
#
# Then:  bash deploy/install_jiraiya_mini.sh
set -eu
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
UID_N="$(id -u)"
LA="$HOME/Library/LaunchAgents"
CFG="$HOME/.config/recruiting-report"

echo "== Jiraiya install =="
echo "repo: $REPO"

# 1) latest code
git pull --ff-only 2>&1 | tail -2 || echo "(git pull skipped/failed — continuing)"

# 2) token check (can't be moved for you — must exist here)
for t in dd-bot-token dd-app-token; do
  if [ ! -s "$CFG/$t" ]; then
    echo "!! MISSING $CFG/$t — place it first:"
    echo "   mkdir -p $CFG && pbpaste > $CFG/$t   (after copying the token)"
    exit 2
  fi
done
echo "tokens: present"

mkdir -p "$LA" "$REPO/output/logs"

_write_plist () {  # $1=label  $2=ProgramArgs-script  $3=extra-keys
  cat > "$LA/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$1</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$REPO/deploy/$2</string></array>
    <key>WorkingDirectory</key><string>$REPO</string>
    <key>EnvironmentVariables</key><dict>
        <key>PYTHONPATH</key><string>$REPO</string>
    </dict>
$3
    <key>StandardOutPath</key><string>$REPO/output/logs/$1.out.log</string>
    <key>StandardErrorPath</key><string>$REPO/output/logs/$1.err.log</string>
</dict>
</plist>
PLIST
}

# always-on listener
_write_plist com.alphalete.jiraiya-bot jiraiya_bot.sh \
"    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>"

# 3am nightly harvest
_write_plist com.alphalete.due-diligence-harvest due_diligence_harvest.sh \
"    <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>"

for L in com.alphalete.jiraiya-bot com.alphalete.due-diligence-harvest; do
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null || true
  launchctl enable "gui/$UID_N/$L" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$LA/$L.plist"
  echo "loaded $L"
done

sleep 5
echo "== jiraiya-bot status =="
launchctl print "gui/$UID_N/com.alphalete.jiraiya-bot" 2>/dev/null | grep -E "state =|pid =" | head -2 || true
tail -2 "$REPO/output/logs/com.alphalete.jiraiya-bot.out.log" 2>/dev/null || true
echo "Done. If it says 'connected — /dd is live', Jiraiya is running 24/7 here."
