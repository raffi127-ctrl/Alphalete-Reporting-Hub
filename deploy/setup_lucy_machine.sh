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

# ----- Timezone + clock FIRST: launchd caches the TZ, and a skewed clock is
# a classic cause of "not currently available from the Software Update server"
bold "[1/7] Timezone → America/Chicago + network time"
sudo systemsetup -settimezone America/Chicago >/dev/null 2>&1 || true
if [ "$(sudo systemsetup -gettimezone 2>/dev/null)" != "Time Zone: America/Chicago" ]; then
    MANUAL+=("System Settings → General → Date & Time → set time zone to Chicago")
fi
sudo systemsetup -setusingnetworktime on >/dev/null 2>&1 || true
sudo sntp -sS time.apple.com >/dev/null 2>&1 || true

# ----- Apple Command Line Tools. The GUI popup route (xcode-select --install)
# flaked on Lucy 3's first setup ("not currently available from the Software
# Update server"), so fetch through softwareupdate directly: the on-demand
# marker file makes the CLT package appear in the catalog listing.
if ! xcode-select -p >/dev/null 2>&1; then
    bold "[2/7] Installing Apple's Command Line Tools (5-15 min — grab a coffee)"
    sudo touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    CLT_LABEL="$(softwareupdate -l 2>/dev/null \
        | awk -F'Label: ' '/Label: Command Line Tools/{print $2}' | tail -1)"
    if [ -n "$CLT_LABEL" ]; then
        echo "Found: $CLT_LABEL"
        sudo softwareupdate -i "$CLT_LABEL" --verbose || true
    fi
    sudo rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    # A finished install sometimes still needs the pointer set
    if ! xcode-select -p >/dev/null 2>&1 \
            && [ -d /Library/Developer/CommandLineTools ]; then
        sudo xcode-select --switch /Library/Developer/CommandLineTools || true
    fi
    if ! xcode-select -p >/dev/null 2>&1; then
        bold "❌ Apple's servers would not hand over the Command Line Tools."
        echo "Two things to try, then re-run this same setup command:"
        echo "  1. System Settings → General → Software Update — install any"
        echo "     pending macOS update, reboot, re-run this."
        echo "  2. If that changes nothing: developer.apple.com/download/all"
        echo "     (free Apple ID sign-in) → download 'Command Line Tools for"
        echo "     Xcode' for this macOS version → install the .dmg → re-run."
        read -p "Press Enter to close."
        exit 1
    fi
else
    bold "[2/7] Apple's Command Line Tools already installed ✓"
fi

# ----- Never sleep (pmset works everywhere sudo does). disablesleep 1 is
# the hard switch — timers alone left Lucy 3 with 'sleep NOT prevented'
# on the diag (2026-08-21).
bold "[3/7] Disabling sleep"
if ! sudo pmset -a sleep 0 displaysleep 0 disksleep 0 womp 1 disablesleep 1; then
    MANUAL+=("System Settings → Energy → turn off 'Put hard disks to sleep' / set sleep to Never")
fi

# ----- SSH (Remote Login)
bold "[4/7] Turning on SSH (Remote Login)"
sudo systemsetup -setremotelogin on >/dev/null 2>&1 || true
if ! sudo systemsetup -getremotelogin 2>/dev/null | grep -q "On"; then
    MANUAL+=("System Settings → General → Sharing → turn ON Remote Login")
fi

# ----- Screen Sharing
bold "[5/7] Turning on Screen Sharing"
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist 2>/dev/null || true
if ! sudo launchctl list 2>/dev/null | grep -q screensharing; then
    MANUAL+=("System Settings → General → Sharing → turn ON Screen Sharing")
fi

# ----- Team installer (idempotent: safe if partly installed already)
bold "[6/8] Running the team installer (GitHub sign-in opens in the browser)"
curl -fsSL -o /tmp/Install-Recruiting-Report.command \
    https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub/releases/download/v0.1.0/Install-Recruiting-Report.command
bash /tmp/Install-Recruiting-Report.command || {
    echo "Installer did not finish — fix what it printed, then re-run this same command."
    exit 1
}

# ----- Google Sheets sign-in (one-time; without it the Hub shows a red
# token error and the run feed is blind — Lucy 3's first launch, 2026-08-21)
if [ -f "$HOME/.config/recruiting-report/oauth-token.json" ]; then
    bold "[7/8] Google Sheets already authorized ✓"
else
    bold "[7/8] Google Sheets sign-in — a browser will open"
    echo "Sign in with the alphaletereporting@gmail.com Google account and click Allow."
    (cd "$HOME/recruiting-report" \
        && ./.venv/bin/python -m automations.recruiting_report.sheets_auth) || \
        MANUAL+=("Google sign-in didn't finish — run: cd ~/recruiting-report && ./.venv/bin/python -m automations.recruiting_report.sheets_auth")
fi

# ----- Identity + poller
bold "[8/8] Naming this machine '$NAME' + installing the remote-control poller"
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
