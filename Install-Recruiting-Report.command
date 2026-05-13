#!/bin/bash
#
# Recruiting Report — one-click installer
# Double-click this file to set up the dashboard on a new Mac.
# No Terminal commands to copy/paste. Takes ~5 minutes.
#
# What this does (so it's not a black box):
#   1. Installs Homebrew if missing (the Mac package manager)
#   2. Installs the GitHub CLI (`gh`)
#   3. Asks you to sign in to GitHub in your browser (one click)
#   4. Downloads the dashboard repo to ~/recruiting-report
#   5. Runs install.sh inside the repo (Python venv, packages, config)
#   6. Opens the install folder so you can drag the launcher to your Dock
#

set -e

# --- Make this script's output visible when double-clicked --------------
# macOS opens .command files in Terminal automatically. Pretty headers help.
REPO_OWNER="raffi127-ctrl"
REPO_NAME="Alphalete-Reporting-Hub"
REPO_FULL="${REPO_OWNER}/${REPO_NAME}"
INSTALL_DIR="$HOME/recruiting-report"

bold()  { printf "\033[1m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
blue()  { printf "\033[34m%s\033[0m\n" "$1"; }

show_dialog() {
    # $1 = title, $2 = message, $3 = icon (note|stop|caution)
    osascript -e "display dialog \"$2\" with title \"$1\" buttons {\"OK\"} default button \"OK\" with icon ${3:-note}" >/dev/null 2>&1 || true
}

on_error() {
    red ""
    red "════════════════════════════════════════════════"
    red "  ❌ Something went wrong."
    red "════════════════════════════════════════════════"
    echo ""
    echo "Take a screenshot of this window and send it to Megan."
    echo "Then close this window."
    show_dialog "Recruiting Report — Setup Failed" "Something went wrong. Take a screenshot of the Terminal window and send it to Megan." "stop"
    # Keep window open
    echo ""
    read -p "Press Enter to close this window."
    exit 1
}
trap on_error ERR

clear
bold "════════════════════════════════════════════════"
bold "  🐺  Recruiting Report — One-Click Setup"
bold "════════════════════════════════════════════════"
echo ""
echo "This will install everything you need. Takes ~5 minutes."
echo "You'll need to:"
echo "  • Enter your Mac password once (for Homebrew)"
echo "  • Sign in to GitHub in your browser (one click)"
echo ""
read -p "Press Enter to begin..."
echo ""

# ------------------------------------------------------------------
# 1. Homebrew
# ------------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
    bold "[1/5] Installing Homebrew (the Mac package manager)…"
    echo "      (You may be asked for your Mac password — type it and press Enter."
    echo "       You won't see the characters as you type. That's normal.)"
    echo ""
    # No NONINTERACTIVE here — Homebrew needs to be able to prompt for the
    # sudo password. With NONINTERACTIVE set, Homebrew bails immediately if
    # the user isn't already a passwordless-sudo admin, which fails on most
    # Macs in the wild. Letting it prompt works in Terminal (which is what
    # macOS uses to open .command files on double-click).
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Make brew available in this shell session
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    green "[1/5] Homebrew already installed ✓"
fi

# ------------------------------------------------------------------
# 2. GitHub CLI
# ------------------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
    bold "[2/5] Installing the GitHub CLI…"
    brew install gh
else
    green "[2/5] GitHub CLI already installed ✓"
fi

# ------------------------------------------------------------------
# 3. GitHub auth (opens browser)
# ------------------------------------------------------------------
if ! gh auth status >/dev/null 2>&1; then
    bold "[3/5] Signing you in to GitHub…"
    echo ""
    echo "      Your browser will open in a moment."
    echo "      A code like XXXX-XXXX will appear here — paste it in the browser"
    echo "      and click Authorize. Then come back to this window."
    echo ""
    sleep 2
    gh auth login --hostname github.com --git-protocol https --web
else
    green "[3/5] Already signed in to GitHub ✓"
fi

# ------------------------------------------------------------------
# 4. Clone the repo
# ------------------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
    green "[4/5] Repo already at $INSTALL_DIR — updating…"
    git -C "$INSTALL_DIR" pull --ff-only || true
else
    bold "[4/5] Downloading the dashboard to $INSTALL_DIR…"
    gh repo clone "$REPO_FULL" "$INSTALL_DIR"
fi

# ------------------------------------------------------------------
# 5. Run the inner installer
# ------------------------------------------------------------------
bold "[5/5] Setting up Python + packages (this takes a minute)…"
bash "$INSTALL_DIR/install.sh"

# ------------------------------------------------------------------
# Install the .app to /Applications and pin it to the Dock automatically.
# Sequoia's Dock refuses drags of ad-hoc-signed apps from non-/Applications
# folders (shows trash-only drop target), so we:
#   1. Copy the .app to /Applications (Gatekeeper-blessed location)
#   2. Rewrite its launcher to point at this user's $INSTALL_DIR (the
#      relative-path resolution in the repo copy breaks once moved)
#   3. Re-sign ad-hoc + clear quarantine
#   4. Write the pin directly into the Dock prefs (no drag needed)
# ------------------------------------------------------------------
APP_SRC="$INSTALL_DIR/Alphalete Reporting Hub.app"
APP_DST="/Applications/Alphalete Reporting Hub.app"

if [ -d "$APP_SRC" ]; then
    bold "Pinning the 🐺 wolf icon to your Dock…"

    # Replace any existing /Applications copy with the freshly-installed one
    rm -rf "$APP_DST"
    cp -R "$APP_SRC" "$APP_DST"

    # Hardcode this user's repo path in the installed launcher so it works
    # from /Applications (relative-path resolution doesn't work once moved).
    cat > "$APP_DST/Contents/MacOS/launcher" <<EOF
#!/bin/bash
set -e
open "$INSTALL_DIR/launch_dashboard.command"
EOF
    chmod +x "$APP_DST/Contents/MacOS/launcher"

    # Re-sign ad-hoc (launcher changed) and clear quarantine attrs
    codesign --force --deep -s - "$APP_DST" >/dev/null 2>&1 || true
    xattr -dr com.apple.quarantine "$APP_DST" 2>/dev/null || true
    xattr -dr com.apple.provenance "$APP_DST" 2>/dev/null || true

    # Add to Dock if not already pinned (idempotent on re-install)
    if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "com.alphalete.reporting-hub"; then
        defaults write com.apple.dock persistent-apps -array-add '<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>/Applications/Alphalete Reporting Hub.app</string><key>_CFURLStringType</key><integer>0</integer></dict></dict><key>tile-type</key><string>file-tile</string></dict>'
        killall Dock 2>/dev/null || true
    fi
fi

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
green ""
green "════════════════════════════════════════════════"
green "  ✅ All set!"
green "════════════════════════════════════════════════"
echo ""
echo "The 🐺 Alphalete Reporting Hub icon is now in your Dock."
echo "Click it any time you want to open the hub."
echo ""

show_dialog "Recruiting Report — Ready!" "Setup complete. The 🐺 wolf icon is now in your Dock — click it any time to open the hub." "note"

echo ""
read -p "Press Enter to close this window."
