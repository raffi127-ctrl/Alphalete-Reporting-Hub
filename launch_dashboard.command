#!/bin/bash
# Double-click this file to launch the Reports dashboard.
# Binds to all network interfaces so Tailscale peers can reach it.

cd "$(dirname "$0")"

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
