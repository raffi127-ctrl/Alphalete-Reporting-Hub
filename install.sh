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

# 1a. Pick a Python that ships prebuilt packages for all our deps. Python
# 3.14 is too new — several deps ('cryptography', pandas, etc.) publish no
# wheels for it yet, so pip falls back to compiling from source (needs Rust +
# OpenSSL + pkg-config) and dies with a wall of errors on a fresh Mac
# (confirmed: Intel Mac on 3.14, 2026-07-03). Prefer a proven version; only
# fall back to bare `python3` if none of the good ones are installed.
PYTHON_BIN=""
for cand in python3.13 python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYTHON_BIN="$cand"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
    PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")"
    case "$PYVER" in
        3.14|3.15|3.16|3.17)
            red "⚠ Only Python $PYVER found — it's too new for prebuilt packages."
            echo "   The install will try to compile from source and will likely fail."
            echo "   Recommended fix:  brew install python@3.13"
            echo "   Then re-run this installer."
            echo
            ;;
    esac
fi
echo "→ Using $(command -v "$PYTHON_BIN" 2>/dev/null || echo "$PYTHON_BIN") ($PYTHON_BIN)"

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
# Validate that any existing .venv is fully working before reusing it. If the
# system Python that built the venv moved/upgraded (e.g. 3.9 → 3.14, or a macOS
# update), the venv's pip SCRIPT keeps a stale shebang and gets run as shell —
# ".venv/bin/pip: line 3: import: command not found" (Carlos 2026-07-04). Test
# via `python -m pip` (not just `import sys`) so a broken pip is caught too,
# then force a clean rebuild — cheaper than repairing a half-broken venv.
if [ -d ".venv" ]; then
    if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
        echo "→ Existing .venv is broken (Python interpreter missing). Rebuilding…"
        rm -rf .venv
    else
        # Also rebuild if the venv is on a different Python than the one we
        # picked above — e.g. an earlier run built it on 3.14 before 3.13 was
        # installed. Reusing that stale venv would keep hitting the wheel
        # problem no matter what the user installs afterward.
        VENV_VER="$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '')"
        WANT_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '')"
        if [ -n "$VENV_VER" ] && [ -n "$WANT_VER" ] && [ "$VENV_VER" != "$WANT_VER" ]; then
            echo "→ Existing .venv is on Python $VENV_VER; rebuilding on $WANT_VER"
            rm -rf .venv
        fi
    fi
fi
if [ ! -d ".venv" ]; then
    echo "→ Creating Python venv"
    "$PYTHON_BIN" -m venv .venv
fi
echo "→ Upgrading pip"
# Always invoke pip as `python -m pip` — never the .venv/bin/pip script — so a
# stale pip shebang (from a moved system Python) can't run pip through the shell.
.venv/bin/python -m pip install --quiet --upgrade pip
echo "→ Installing Python packages (this takes a minute)"
# Force ready-made wheels for the packages that otherwise compile native code
# (cryptography = Rust+OpenSSL; pandas/numpy/pyarrow/pillow/cffi = C). If a
# wheel is missing for this Python, fail FAST with a plain-English fix instead
# of dumping a wall of Rust/compiler errors. Pure-Python deps still install
# normally (they're not in this --only-binary list), so sdist-only packages
# aren't blocked.
if ! .venv/bin/python -m pip install --quiet \
        --only-binary=cryptography,cffi,pandas,numpy,pyarrow,pillow \
        -r automations/recruiting_report/requirements.txt; then
    PYVER="$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
    echo
    red "❌ Couldn't install ready-made packages for Python $PYVER."
    echo "   This Python is too new — some packages (like 'cryptography') don't"
    echo "   publish prebuilt builds for it yet, so they'd have to be compiled"
    echo "   from source (which needs extra developer tools you don't have)."
    echo
    echo "   Easiest fix:"
    echo "     1) Install Python 3.13:   brew install python@3.13"
    echo "     2) Re-run this installer."
    echo
    echo "   (Advanced — to compile anyway: brew install pkgconf openssl@3 rust,"
    echo "    set OPENSSL_DIR=\$(brew --prefix openssl@3), then re-run.)"
    exit 1
fi

# 4. Install the Chromium build for the browser driver. The project uses
# patchright (a Playwright fork). Invoke via `python -m patchright` — NOT the
# .venv/bin/patchright script — so a stale console-script shebang (from a moved
# system Python) can't run it through the shell (Lucy 2 2026-07-07:
# ".venv/bin/patchright: line 2: import: command not found"). Fall back to
# playwright only if patchright isn't importable.
echo "→ Installing Chromium for patchright"
if .venv/bin/python -c "import patchright" 2>/dev/null; then
    .venv/bin/python -m patchright install chromium >/dev/null
elif .venv/bin/python -c "import playwright" 2>/dev/null; then
    .venv/bin/python -m playwright install chromium >/dev/null
else
    red "⚠ neither patchright nor playwright importable in .venv — skipping Chromium install"
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
