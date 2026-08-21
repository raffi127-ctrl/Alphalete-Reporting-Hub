#!/bin/bash
#
# One-shot setup for a NEW Lucy machine (Mac mini runner).
# Does everything a fresh box needs in one run:
#   • system prep: Chicago timezone, never sleep, SSH + Screen Sharing on
#   • the team installer (Homebrew, GitHub sign-in, repo → ~/recruiting-report,
#     Python env, wolf Dock icon)
#   • machine identity (.machine-profile) + the mini_control poller agent
#
# Usage (from Slack, on the new machine's Terminal — quote-free on purpose so
# Slack's smart-quotes can't corrupt it):
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/deploy/setup_lucy_machine.sh -o /tmp/setup_lucy.sh && bash /tmp/setup_lucy.sh Lucy 3
#
# The machine name is everything after the script name ("Lucy 3" above).
# Asks for the Mac password once (sudo) and a GitHub browser sign-in.
#
# Auto-login is deliberately NOT scripted: doing it non-interactively means
# writing the user's password to disk (/etc/kcpassword). It stays a one-click
# manual step, listed at the end.
#
# macOS sometimes refuses systemsetup changes unless Terminal has Full Disk
# Access — every system tweak below is attempted, verified, and anything that
# didn't stick is printed as a manual checklist at the end instead of failing
# the whole run.

set -u

NAME="${*:-Lucy 3}"
MANUAL=()

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }

bold "Setting up '$NAME' — you'll be asked for this Mac's password once."
sudo -v || { echo "Need the Mac password to continue."; exit 1; }

# ----- Timezone FIRST (launchd caches it — agents installed later inherit it)
bold "[1/6] Timezone → America/Chicago"
sudo systemsetup -settimezone America/Chicago >/dev/null 2>&1 || true
if [ "$(sudo systemsetup -gettimezone 2>/dev/null)" != "Time Zone: America/Chicago" ]; then
    MANUAL+=("System Settings → General → Date & Time → set time zone to Chicago")
fi
sudo systemsetup -setusingnetworktime on >/dev/null 2>&1 || true

# ----- Never sleep (pmset works everywhere sudo does)
bold "[2/6] Disabling sleep"
if ! sudo pmset -a sleep 0 displaysleep 0 disksleep 0 womp 1; then
    MANUAL+=("System Settings → Energy → turn off 'Put hard disks to sleep' / set sleep to Never")
fi

# ----- SSH (Remote Login)
bold "[3/6] Turning on SSH (Remote Login)"
sudo systemsetup -setremotelogin on >/dev/null 2>&1 || true
if ! sudo systemsetup -getremotelogin 2>/dev/null | grep -q "On"; then
    MANUAL+=("System Settings → General → Sharing → turn ON Remote Login")
fi

# ----- Screen Sharing
bold "[4/6] Turning on Screen Sharing"
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist 2>/dev/null || true
if ! sudo launchctl list 2>/dev/null | grep -q screensharing; then
    MANUAL+=("System Settings → General → Sharing → turn ON Screen Sharing")
fi

# ----- Team installer (idempotent: safe if partly installed already)
bold "[5/6] Running the team installer (GitHub sign-in opens in the browser)"
curl -fsSL -o /tmp/Install-Recruiting-Report.command \
    https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub/releases/download/v0.1.0/Install-Recruiting-Report.command
bash /tmp/Install-Recruiting-Report.command || {
    echo "Installer did not finish — fix what it printed, then re-run this same command."
    exit 1
}

# ----- Identity + poller
bold "[6/6] Naming this machine '$NAME' + installing the remote-control poller"
echo "$NAME" > "$HOME/recruiting-report/.machine-profile"
cd "$HOME/recruiting-report"
./.venv/bin/python automations/day_orchestrator/install_agent.py mini-control || {
    MANUAL+=("Poller install failed — from ~/recruiting-report run: ./.venv/bin/python automations/day_orchestrator/install_agent.py mini-control")
}

bold "══════════════════════════════════════"
bold "✅ '$NAME' base setup done."
echo ""
echo "Manual steps left (one minute):"
echo "  • System Settings → Users & Groups → turn ON automatic login (not"
echo "    scripted on purpose — doing it in code would store your password)."
for m in "${MANUAL[@]+"${MANUAL[@]}"}"; do
    echo "  • $m"
done
echo ""
echo "Then tell Megan's Claude 'done' — it verifies the rest remotely."
echo "(Site sign-ins — AppStream/ownerville/Tableau — happen later, guided,"
echo " with a person at this keyboard. Reports can't run here until then.)"
read -p "Press Enter to close."
