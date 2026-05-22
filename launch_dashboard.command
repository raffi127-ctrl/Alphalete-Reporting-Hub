#!/bin/bash
# Double-click this file to launch the Reports dashboard.
# Binds to all network interfaces so Tailscale peers can reach it.
# On launch, auto-pulls latest from GitHub if there are no local changes.

cd "$(dirname "$0")"

# ----- Auto-update from GitHub (skips if local edits present) -----
if [ -d .git ]; then
  if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
    echo "→ Checking for updates..."
    git fetch --quiet origin main 2>/dev/null || true
    LOCAL=$(git rev-parse @ 2>/dev/null || echo "")
    REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")
    if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
      echo "→ Updates found — pulling..."
      if git pull --ff-only --quiet origin main; then
        echo "✅ Updated to latest version"
        # Reinstall Python deps if requirements changed
        if git diff HEAD@{1} HEAD --name-only 2>/dev/null | grep -q "requirements.txt"; then
          echo "→ Updating Python packages..."
          ./.venv/bin/pip install --quiet -r automations/recruiting_report/requirements.txt
        fi
      else
        echo "⚠️  Auto-update failed — continuing with current version"
      fi
    else
      echo "✅ Already up to date"
    fi
  else
    echo "→ Local changes detected — skipping auto-update (you're in dev mode)"
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
NATIVE_ARCH="$(arch 2>/dev/null || echo unknown)"
if [ "$NATIVE_ARCH" = "arm64" ]; then
  exec /usr/bin/arch -arm64 ./.venv/bin/python -m streamlit run automations/dashboard.py \
    --server.headless true \
    --server.address 0.0.0.0 \
    --server.port "$PORT"
else
  exec ./.venv/bin/python -m streamlit run automations/dashboard.py \
    --server.headless true \
    --server.address 0.0.0.0 \
    --server.port "$PORT"
fi
