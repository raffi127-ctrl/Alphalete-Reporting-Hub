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
# Validate that any existing .venv has a working Python interpreter
# before reusing it. If the system Python that built the venv has been
# uninstalled/upgraded (e.g. 3.9 → 3.14), the venv's interpreter symlink
# dangles and `.venv/bin/pip` crashes with "import: command not found".
# Detect that and force a clean rebuild — much cheaper than trying to
# repair a half-broken venv. Confirmed root cause for Maud 2026-05-21.
if [ -d ".venv" ]; then
    if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
        echo "→ Existing .venv is broken (Python interpreter missing). Rebuilding…"
        rm -rf .venv
    fi
fi
if [ ! -d ".venv" ]; then
    echo "→ Creating Python venv"
    python3 -m venv .venv
fi
echo "→ Upgrading pip"
.venv/bin/pip install --quiet --upgrade pip
echo "→ Installing Python packages (this takes a minute)"
.venv/bin/pip install --quiet -r automations/recruiting_report/requirements.txt

# 4. Install the Chromium build for the browser driver. The project uses
# patchright (a Playwright fork) — the venv has `.venv/bin/patchright`, NOT
# `.venv/bin/playwright` (the old name broke Camila's install 2026-06-16).
# Prefer patchright; fall back to playwright only if that's what's present.
echo "→ Installing Chromium for patchright"
if [ -x .venv/bin/patchright ]; then
    .venv/bin/patchright install chromium >/dev/null
elif [ -x .venv/bin/playwright ]; then
    .venv/bin/playwright install chromium >/dev/null
else
    red "⚠ neither patchright nor playwright CLI found in .venv — skipping Chromium install"
fi

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

# 6a. Pin the venv's Python to arm64 on Apple Silicon. Apple's universal
# Python.app wrapper sometimes lands on x86_64 when launched via the .app
# or LaunchServices, which then can't load arm64-only wheels (cffi etc.).
# Replacing the symlinked python with a wrapper that forces /usr/bin/arch
# -arm64 + __PYVENV_LAUNCHER__ keeps the venv working regardless of caller.
#
# Version-detection: we don't hardcode 3.9 anymore. Maud's machine
# (2026-05-21) updated Python.org from 3.9 → 3.14 mid-install; the
# original 'python3.9' hardcode meant her launcher invoked a binary that
# no longer existed. Now we detect the actual minor version of the venv
# and wrap whichever 'python3.X' is there.
if [ "$(uname -m 2>/dev/null)" = "arm64" ] && [ ! -f .venv/bin/.arm64-wrapped ]; then
    # Find the actual python3.X binary in the venv (whatever minor version)
    VENV_PYTHON_BIN=""
    for cand in .venv/bin/python3.[0-9] .venv/bin/python3.[0-9][0-9]; do
        if [ -f "$cand" ]; then
            VENV_PYTHON_BIN="$cand"
            break
        fi
    done
    if [ -n "$VENV_PYTHON_BIN" ]; then
        # python3.9, python3.10, python3.14 etc. — the version-specific binary
        VENV_PY_NAME="${VENV_PYTHON_BIN##*/}"   # e.g. 'python3.14'
        # Only Python.app/Contents/MacOS/Python honors __PYVENV_LAUNCHER__.
        # bin/python3.X does not, so using the readlink target directly would
        # bypass the venv's site-packages and break streamlit imports.
        REAL_PYTHON=""
        if [ -L "$VENV_PYTHON_BIN" ]; then
            RESOLVED="$(readlink -f "$VENV_PYTHON_BIN" 2>/dev/null || true)"
            if [ -n "$RESOLVED" ]; then
                VERSION_ROOT="${RESOLVED%/bin/python*}"
                CANDIDATE="$VERSION_ROOT/Resources/Python.app/Contents/MacOS/Python"
                [ -x "$CANDIDATE" ] && REAL_PYTHON="$CANDIDATE"
            fi
        fi
        if [ -x "$REAL_PYTHON" ]; then
            rm -f .venv/bin/python .venv/bin/python3 "$VENV_PYTHON_BIN"
            cat > "$VENV_PYTHON_BIN" <<WRAP
#!/bin/bash
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
export __PYVENV_LAUNCHER__="\$HERE/$VENV_PY_NAME"
exec /usr/bin/arch -arm64 "$REAL_PYTHON" "\$@"
WRAP
            chmod +x "$VENV_PYTHON_BIN"
            ln -s "$VENV_PY_NAME" .venv/bin/python3
            ln -s "$VENV_PY_NAME" .venv/bin/python
            touch .venv/bin/.arm64-wrapped
            echo "→ Pinned venv Python to arm64 ($VENV_PY_NAME wrapper installed)"
        fi
    fi
fi
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
