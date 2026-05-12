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
