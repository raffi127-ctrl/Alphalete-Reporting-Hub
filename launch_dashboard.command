#!/bin/bash
# Double-click this file to launch the Reports dashboard.
# Binds to all network interfaces so Tailscale peers can reach it.
# On launch, auto-pulls latest from GitHub if there are no local changes.

# macOS 26 (Sequoia) + Python 3.14 regression: subprocess.Popen crashes
# in the child process post-fork inside the Network framework's atfork
# handler ('crashed on child side of fork pre-exec' in the crash dump,
# stack ends in NEFlowDirectorDestroy / nw_settings_child_has_forked).
# The fix is to disable the Obj-C fork-safety check + force Python to
# use posix_spawn() rather than fork() for subprocesses. Both env vars
# are inherited by every Python process the launcher (and the dashboard)
# spawn. Setting NO_PROXY='*' also stops the Network framework's CFNetwork
# proxy lookup from registering the offending atfork handler.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1

# Disable click/colorama's ANSI wrapping. Streamlit's signal_handler calls
# click.secho("Stopping...") which on Windows can re-enter the BufferedWriter
# and crash the Hub server (Eve, 2026-05-22). NO_COLOR is harmless on macOS
# but needs to be set in the launcher BOTH places so the .bat and .command
# stay symmetric — anyone who edits one and forgets the other reintroduces
# the bug on the other OS.
export NO_COLOR=1

cd "$(dirname "$0")"

# ----- Auto-update from GitHub -----
# Two modes, decided by the gitignored `.dev-machine` marker:
#   • DEV machine (marker present): only fast-forward when the tree is clean,
#     so Megan/Claude's uncommitted edits are never discarded.
#   • TEAMMATE machine (no marker): hard-align to origin/main every launch, so
#     a stray tracked change (often just Windows CRLF line-endings) or a wrong
#     branch can NEVER strand them on stale code — the bug that hid every fix
#     from Eve on 2026-05-25.
if [ -d .git ]; then
  PRE_UPDATE_HEAD="$(git rev-parse @ 2>/dev/null || echo "")"
  DID_UPDATE=0

  if [ -f .dev-machine ]; then
    # --- DEV machine: protect local edits (only update when tree is clean) ---
    if [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
      echo "→ Checking for updates (dev)..."
      git fetch --quiet origin main 2>/dev/null || true
      LOCAL=$(git rev-parse @ 2>/dev/null || echo "")
      REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")
      if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
        echo "→ Updates found — pulling..."
        if git pull --ff-only --quiet origin main; then
          echo "✅ Updated to latest version"; DID_UPDATE=1
        else
          echo "⚠️  Auto-update failed — continuing with current version"
        fi
      else
        echo "✅ Already up to date"
      fi
    else
      echo "→ Local changes detected — skipping auto-update (dev mode)"
    fi
  else
    # --- TEAMMATE machine: force-align to origin/main, every launch ---
    echo "→ Syncing to latest..."
    if git fetch --quiet origin main 2>/dev/null && \
       git checkout -f -B main origin/main >/dev/null 2>&1; then
      NEW_HEAD="$(git rev-parse @ 2>/dev/null || echo "")"
      [ "$PRE_UPDATE_HEAD" != "$NEW_HEAD" ] && DID_UPDATE=1
      echo "✅ On latest: $(git log -1 --format='%h %s' 2>/dev/null)"
    else
      echo ""
      echo "════════════════════════════════════════════════════════════════"
      echo "⚠️   COULDN'T SYNC TO LATEST — you may be running OLD code."
      echo "     If a report looks wrong, tell Megan. Manual fix (this folder):"
      echo "        git fetch origin && git checkout -f -B main origin/main"
      echo "════════════════════════════════════════════════════════════════"
      echo ""
    fi
  fi

  # ----- Always sync Python packages on launch.
  # Previously gated on "requirements.txt was in this pull's diff", which
  # silently missed teammates whose pull fell outside the change window
  # (Eve hit ModuleNotFoundError: slack_sdk on 2026-05-28). pip install
  # --quiet is ~2-4s when everything's already in place — cheap insurance.
  # Invoke pip as `python -m pip` (never the .venv/bin/pip script) so a stale
  # pip shebang from a moved system Python can't run pip through the shell.
  if [ -x .venv/bin/python ]; then
    echo "→ Syncing Python packages..."
    ./.venv/bin/python -m pip install --quiet -r automations/recruiting_report/requirements.txt 2>/dev/null \
      || echo "⚠️  pip install hit an error (offline?) — reports will crash with ModuleNotFoundError if a dep is missing"
  fi
  # Invoke patchright as `python -m patchright` (never the .venv/bin/patchright
  # script) so a stale console-script shebang can't run it through the shell.
  if [ ! -f .venv/.patchright_chromium_installed ] && ./.venv/bin/python -c "import patchright" 2>/dev/null; then
    echo "→ First-time: installing Chromium for patchright (one-time, ~150MB)..."
    if ./.venv/bin/python -m patchright install chromium >/dev/null 2>&1; then
      touch .venv/.patchright_chromium_installed
      echo "✅ Chromium installed for patchright"
    else
      echo "⚠️  patchright Chromium install failed — run: ./.venv/bin/python -m patchright install chromium"
    fi
  fi
fi

# ----- One-time prompt: new .app icon ready to drag to the Dock -----
# Anyone who installed before the .app bundle existed is still launching
# from launch_dashboard.command (paper icon). The first time they relaunch
# after the auto-pull, show a friendly Finder + dialog combo so they can
# swap to the on-brand icon. A marker file silences the prompt afterward.
# Find whichever python3.X exists in the venv (any minor version).
# Teammates who upgrade Python.org mid-life can end up with a venv where
# the original 'python3.9' (or whatever) binary is gone but a newer one
# (python3.14) is sitting there — and .venv/bin/python is then a stale
# broken symlink. Detect the live binary up front so the rest of this
# script can self-heal regardless of minor version.
VENV_PY_BIN=""
if [ -d .venv/bin ]; then
  for cand in .venv/bin/python3.[0-9] .venv/bin/python3.[0-9][0-9]; do
    if [ -f "$cand" ]; then VENV_PY_BIN="$cand"; break; fi
  done
fi

# If .venv/bin/python is missing or broken, recreate it from the live
# python3.X binary. Without this, `exec ./.venv/bin/python …` at the end
# of this script fails silently and the Hub icon appears "broken" — same
# trap that hit Maud after her Python 3.9 → 3.14 upgrade.
if [ -n "$VENV_PY_BIN" ] && [ ! -x .venv/bin/python ]; then
  VENV_PY_NAME="${VENV_PY_BIN##*/}"
  (cd .venv/bin && ln -sf "$VENV_PY_NAME" python && ln -sf "$VENV_PY_NAME" python3)
  echo "→ Healed .venv/bin/python → $VENV_PY_NAME (was missing)"
fi

# Pin the venv's Python to arm64 on Apple Silicon. The CommandLineTools
# Python is universal and sometimes resolves to its x86_64 slice when
# launched via Python.app/LaunchServices, which then can't load arm64-
# only wheels like _cffi_backend. Replacing the venv's python symlink
# with a wrapper that forces /usr/bin/arch -arm64 sidesteps it entirely.
# (install.sh sets this up on fresh installs; this block catches existing
# clones that pre-date the fix.)
if [ "$(uname -m 2>/dev/null)" = "arm64" ] && [ -n "$VENV_PY_BIN" ] && [ ! -f .venv/bin/.arm64-wrapped ]; then
  VENV_PY_NAME="${VENV_PY_BIN##*/}"
  # Only Python.app/Contents/MacOS/Python honors __PYVENV_LAUNCHER__;
  # bin/python3.X does not. Map the resolved framework version root to
  # its Python.app variant so venv site-packages stay discoverable.
  REAL_PYTHON=""
  if [ -L "$VENV_PY_BIN" ]; then
    RESOLVED="$(readlink -f "$VENV_PY_BIN" 2>/dev/null || true)"
    if [ -n "$RESOLVED" ]; then
      VERSION_ROOT="${RESOLVED%/bin/python*}"
      CANDIDATE="$VERSION_ROOT/Resources/Python.app/Contents/MacOS/Python"
      [ -x "$CANDIDATE" ] && REAL_PYTHON="$CANDIDATE"
    fi
  fi
  if [ -x "$REAL_PYTHON" ]; then
    rm -f .venv/bin/python .venv/bin/python3 "$VENV_PY_BIN"
    cat > "$VENV_PY_BIN" <<WRAP
#!/bin/bash
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
export __PYVENV_LAUNCHER__="\$HERE/$VENV_PY_NAME"
exec /usr/bin/arch -arm64 "$REAL_PYTHON" "\$@"
WRAP
    chmod +x "$VENV_PY_BIN"
    ln -s "$VENV_PY_NAME" .venv/bin/python3
    ln -s "$VENV_PY_NAME" .venv/bin/python
    touch .venv/bin/.arm64-wrapped
    echo "→ Pinned venv Python to arm64 ($VENV_PY_NAME wrapper installed)"
  fi
fi

DASHBOARD_APP="$PWD/Alphalete Reporting Hub.app"
APP_INSTALLED="/Applications/Alphalete Reporting Hub.app"
BUNDLE_SHA_MARKER="$HOME/.config/recruiting-report/.bundle-sha"
if [ -d "$DASHBOARD_APP" ]; then
  # Keep the wolf .app in /Applications continually in sync with the repo
  # version, and ensure it's pinned to the Dock. Sequoia's Dock refuses
  # drags of ad-hoc-signed apps from non-/Applications folders, so the
  # /Applications copy is mandatory for Dock pinning.
  #
  # Re-sync triggers when:
  #   • /Applications copy is missing (first run or user trashed it), OR
  #   • The git commit that last touched the .app in the repo has changed
  #     since we last installed it (any future bundle update flows through).
  NEEDS_DOCK_REFRESH=0
  CURRENT_BUNDLE_SHA="$(git log -1 --format=%H -- "$DASHBOARD_APP" 2>/dev/null || true)"
  INSTALLED_BUNDLE_SHA="$(cat "$BUNDLE_SHA_MARKER" 2>/dev/null || true)"

  NEEDS_BUNDLE_SYNC=0
  if [ ! -d "$APP_INSTALLED" ]; then
    NEEDS_BUNDLE_SYNC=1
  elif [ -n "$CURRENT_BUNDLE_SHA" ] && [ "$CURRENT_BUNDLE_SHA" != "$INSTALLED_BUNDLE_SHA" ]; then
    NEEDS_BUNDLE_SYNC=1
  fi

  if [ "$NEEDS_BUNDLE_SYNC" = "1" ]; then
    rm -rf "$APP_INSTALLED" 2>/dev/null || true
    if cp -R "$DASHBOARD_APP" "$APP_INSTALLED" 2>/dev/null; then
      # Installed copy needs an absolute path to this user's repo
      # (relative-path resolution from inside /Applications would break).
      cat > "$APP_INSTALLED/Contents/MacOS/launcher" <<EOF
#!/bin/bash
set -e
open "$PWD/launch_dashboard.command"
EOF
      chmod +x "$APP_INSTALLED/Contents/MacOS/launcher" 2>/dev/null || true
      codesign --force --deep -s - "$APP_INSTALLED" >/dev/null 2>&1 || true
      xattr -dr com.apple.quarantine "$APP_INSTALLED" 2>/dev/null || true
      xattr -dr com.apple.provenance "$APP_INSTALLED" 2>/dev/null || true
      mkdir -p "$(dirname "$BUNDLE_SHA_MARKER")" 2>/dev/null || true
      [ -n "$CURRENT_BUNDLE_SHA" ] && echo "$CURRENT_BUNDLE_SHA" > "$BUNDLE_SHA_MARKER" 2>/dev/null || true
      NEEDS_DOCK_REFRESH=1
    fi
  fi

  if [ -d "$APP_INSTALLED" ]; then
    if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "com.alphalete.reporting-hub"; then
      defaults write com.apple.dock persistent-apps -array-add '<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>/Applications/Alphalete Reporting Hub.app</string><key>_CFURLStringType</key><integer>0</integer></dict></dict><key>tile-type</key><string>file-tile</string></dict>' 2>/dev/null && NEEDS_DOCK_REFRESH=1
    fi
  fi

  if [ "$NEEDS_DOCK_REFRESH" = "1" ]; then
    killall Dock 2>/dev/null || true
  fi
fi


# If a previous dashboard is still running on port 8501, kill it cleanly
# so we always start fresh. Avoids "Port 8501 is already in use" errors.
PORT=8501
EXISTING_PID="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)"
if [ -n "$EXISTING_PID" ]; then
  echo "→ Stopping previous dashboard (pid $EXISTING_PID) on port $PORT"
  kill "$EXISTING_PID" 2>/dev/null || true
  # Give it a moment to release the port
  for i in 1 2 3 4 5; do
    sleep 1
    if [ -z "$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)" ]; then
      break
    fi
  done
  # Force-kill if still hanging on
  STILL="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$STILL" ]; then
    kill -9 "$STILL" 2>/dev/null || true
    sleep 1
  fi
fi

# Open the browser to the dashboard a couple seconds after Streamlit starts
( sleep 3 && open "http://localhost:$PORT" ) &

# On Apple Silicon, force the universal-binary Python to run native arm64.
# Without this, the .app launcher inherits an x86_64 context (Rosetta) and
# fails to load arm64-only .so files like _cffi_backend.so. We invoke
# `python -m streamlit` directly instead of the .venv/bin/streamlit shim;
# the shim uses a sh `exec python "$0"` trick that loses the arch context
# in transit, so `arch -arm64 ./streamlit` runs as x86_64 anyway.
# --server.fileWatcherType=none: disable Streamlit's auto-reload-on-file-change.
# The Hub spawns report subprocesses that write to output/logs/active/*.log,
# and Streamlit's default watcher detects those writes and tries to rerun the
# dashboard mid-flight. On Windows that rerun trips through colorama and
# crashes the Hub with 'RuntimeError: reentrant call inside <_io.BufferedWriter>'
# (Eve, 2026-05-22). Teammates get new code via git pull + Hub restart anyway.
NATIVE_ARCH="$(arch 2>/dev/null || echo unknown)"
if [ "$NATIVE_ARCH" = "arm64" ]; then
  exec /usr/bin/arch -arm64 ./.venv/bin/python -m streamlit run automations/dashboard.py \
    --server.headless true \
    --server.address 0.0.0.0 \
    --server.port "$PORT" \
    --server.fileWatcherType=none
else
  exec ./.venv/bin/python -m streamlit run automations/dashboard.py \
    --server.headless true \
    --server.address 0.0.0.0 \
    --server.port "$PORT" \
    --server.fileWatcherType=none
fi
