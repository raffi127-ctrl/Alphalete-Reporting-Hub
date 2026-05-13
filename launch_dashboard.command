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
DASHBOARD_APP="$PWD/Alphalete Reporting Hub.app"
APP_ONBOARD_MARKER="$HOME/.config/recruiting-report/.app-icon-onboarded"
if [ -d "$DASHBOARD_APP" ]; then
  # Ad-hoc code-sign the .app every launch if it isn't already signed.
  # Signatures don't ride along through git clone (per-machine xattrs +
  # CodeResources), so without this Sequoia refuses to drop the icon
  # onto the Dock.
  if command -v codesign >/dev/null 2>&1; then
    if ! codesign --verify --no-strict "$DASHBOARD_APP" 2>/dev/null; then
      codesign --force --deep --sign - "$DASHBOARD_APP" 2>/dev/null || true
      LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
      [ -x "$LSREG" ] && "$LSREG" -f "$DASHBOARD_APP" 2>/dev/null || true
    fi
  fi
  if [ ! -f "$APP_ONBOARD_MARKER" ]; then
    echo ""
    echo "════════════════════════════════════════════════"
    echo "  🐺  New: dedicated app icon for your Dock"
    echo "════════════════════════════════════════════════"
    echo "  A wolf-shield app just landed in your repo. Drag it onto"
    echo "  your Dock so the hub gets a proper on-brand icon."
    echo ""
    open -R "$DASHBOARD_APP" 2>/dev/null || true
    osascript -e 'display dialog "🐺 New Dock icon ready!\n\nA Finder window just opened showing \"Alphalete Reporting Hub\" — the wolf-shield app.\n\n• Drag it onto the right side of your Dock\n• (Optional) Drag the old paper-icon launcher off your Dock\n\nFrom now on, click the wolf to open the hub." with title "Alphalete Reporting Hub — Upgraded Dock Icon" buttons {"Got it"} default button "Got it" with icon note' >/dev/null 2>&1 || true
    mkdir -p "$(dirname "$APP_ONBOARD_MARKER")" 2>/dev/null || true
    touch "$APP_ONBOARD_MARKER" 2>/dev/null || true
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

exec ./.venv/bin/streamlit run automations/dashboard.py \
  --server.headless true \
  --server.address 0.0.0.0 \
  --server.port "$PORT"
