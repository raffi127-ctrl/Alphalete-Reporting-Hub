#!/bin/bash
# Recruiting Report — one-shot installer for new operators (Maud, Eve, etc.)
#
# Run this in Terminal:
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/install.sh | bash
#
# Or if you've already cloned the repo:
#   bash install.sh

set -e

INSTALL_DIR="${INSTALL_DIR:-$HOME/recruiting-report}"
REPO_URL="${REPO_URL:-https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub.git}"
PROD_SHEET_ID="1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

bold "════════════════════════════════════════════════"
bold "  Recruiting Report — installer"
bold "════════════════════════════════════════════════"
echo

# 1. Check prerequisites
if ! command -v python3 >/dev/null; then
    red "❌ Python 3 not found."
    echo "   Install it: https://www.python.org/downloads/macos/"
    exit 1
fi

if ! command -v git >/dev/null; then
    echo "→ git not found. Installing Xcode Command Line Tools (a popup will appear, click Install)…"
    xcode-select --install || true
    echo "   When the install finishes, re-run this script."
    exit 1
fi

# 2. Clone or update the repo
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "→ Updating existing install at $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
elif [ -d "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    # Already inside the repo? (running from local clone)
    if [ -f "$INSTALL_DIR/automations/recruiting_report/fill.py" ]; then
        echo "→ Using existing files at $INSTALL_DIR"
    else
        red "❌ $INSTALL_DIR exists but doesn't look like the project. Move/rename it and re-run."
        exit 1
    fi
else
    echo "→ Cloning into $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# 3. Set up Python venv + install packages
if [ ! -d ".venv" ]; then
    echo "→ Creating Python venv"
    python3 -m venv .venv
fi
echo "→ Upgrading pip"
.venv/bin/pip install --quiet --upgrade pip
echo "→ Installing Python packages (this takes a minute)"
.venv/bin/pip install --quiet -r automations/recruiting_report/requirements.txt

# 4. Install Playwright Chromium (required even though we use real Chrome — provides Playwright runtime)
echo "→ Installing Playwright Chromium"
.venv/bin/playwright install chromium >/dev/null

# 5. Write config (Sheet ID)
CONFIG_DIR="$HOME/.config/recruiting-report"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/config.json" <<EOF
{"spreadsheet_id": "$PROD_SHEET_ID"}
EOF
echo "→ Wrote $CONFIG_DIR/config.json (Sheet ID baked in)"

# 5b. Auto-install the bundled Pack Pass (oauth-client.json) so the user
#     skips the preflight setup screen on first dashboard launch.
if [ -f "$INSTALL_DIR/oauth-client.json" ]; then
    cp "$INSTALL_DIR/oauth-client.json" "$CONFIG_DIR/oauth-client.json"
    echo "→ Installed Pack Pass at $CONFIG_DIR/oauth-client.json"
else
    echo "→ ⚠️  No bundled Pack Pass found in repo. You'll be asked to drop it in via the dashboard on first launch."
fi

# 6. Make the dashboard launcher (.command) and the .app's inner launcher
# both executable. Git preserves +x for both, but re-asserting here keeps
# things working even if someone copied the files via a tool that strips
# the bit.
chmod +x launch_dashboard.command 2>/dev/null || true
chmod +x "Alphalete Reporting Hub.app/Contents/MacOS/launcher" 2>/dev/null || true
# Ad-hoc code-sign the .app so macOS Sequoia accepts it onto the Dock.
# Signatures don't survive git clone (they're in xattrs + per-machine
# CodeResources), so this has to be redone on every fresh install.
if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "Alphalete Reporting Hub.app" 2>/dev/null || true
fi
# Register with LaunchServices so Finder + Dock recognize it cleanly.
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
if [ -x "$LSREG" ]; then
    "$LSREG" -f "Alphalete Reporting Hub.app" 2>/dev/null || true
fi
# Touch the .app so Finder picks up its icon resources fresh on first show.
touch "Alphalete Reporting Hub.app" 2>/dev/null || true

# 7. Done
echo
green "════════════════════════════════════════════════"
green "  ✅ Install complete!"
green "════════════════════════════════════════════════"
cat <<EOF

ONE LAST STEP:

  Open Finder → go to "$INSTALL_DIR"
  Drag "Alphalete Reporting Hub" (the 🐺 wolf icon) onto your Dock.

DAILY USE:

  • Click the Alphalete Reporting Hub icon in your Dock
  • Browser opens with the Alphalete Reporting Hub
  • Sign in with your Pack Access password
  • Click "Launch Chrome" (only the first time each day) → log in to AppStream
  • Click "Run Daily Focus" or "Run Weekly Report"

  First time you run, a Google sign-in window opens.
  Use your work email (the one with access to the Sheet).

EOF
