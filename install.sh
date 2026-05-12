#!/bin/bash
# Recruiting Report — one-shot installer for new operators (Maud, Eve, etc.)
#
# Run this in Terminal:
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Daily-Focus-Report/main/install.sh | bash
#
# Or if you've already cloned the repo:
#   bash install.sh

set -e

INSTALL_DIR="${INSTALL_DIR:-$HOME/recruiting-report}"
REPO_URL="${REPO_URL:-https://github.com/raffi127-ctrl/Daily-Focus-Report.git}"
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

# 6. Make the dashboard launcher double-clickable
chmod +x launch_dashboard.command 2>/dev/null || true

# 7. Done
echo
green "════════════════════════════════════════════════"
green "  ✅ Install complete!"
green "════════════════════════════════════════════════"
cat <<EOF

ONE-TIME SETUP STILL NEEDED:

  1. Get oauth-client.json from Megan (she'll send via Slack).
     Save it to:
         $CONFIG_DIR/oauth-client.json

  2. Open Finder → go to "$INSTALL_DIR"
     Drag "launch_dashboard.command" to your Dock for easy access.

DAILY USE:

  • Double-click launch_dashboard.command
  • Browser opens with the dashboard
  • Click "Launch Chrome" (only the first time each day) → log in to AppStream
  • Click "Run Daily Focus" or "Run Weekly Report"

  First time you run, a Google sign-in window opens.
  Use your work email (the one with access to the Sheet).

EOF
