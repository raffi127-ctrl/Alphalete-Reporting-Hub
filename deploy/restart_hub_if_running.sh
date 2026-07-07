#!/bin/bash
# Bounce the local Hub (Streamlit) IFF one is already running on THIS machine.
#
# Why this exists — the Lucy 1 crash on 2026-07-07:
#   The Hub server is a long-lived FOREGROUND Streamlit process launched with
#   its file watcher disabled (launch_dashboard.command --fileWatcherType=none).
#   When new code lands on the machine WITHOUT a relaunch — a local `git commit`
#   on the dev/mini box, or day_orchestrator.sh's 4am `git pull` — the running
#   server keeps the OLD line numbers in memory while inspect.getsource (which
#   Streamlit calls to build every @st.cache_data key) reads the NEW file on
#   disk. The offsets no longer line up, getsource slices mid-string, and the
#   whole Hub white-screens with:
#     TokenError: unterminated string literal (detected at line NN)
#   Restarting so the in-memory code matches disk is the only fix. This script
#   is the "bounce" wired into the git post-commit / post-merge hooks.
#
# Safe to call from anywhere, on any machine: if nothing is serving the Hub on
# :8501 here it is a no-op. It NEVER spins up a Hub that wasn't already running,
# so teammate boxes / CI / the laptop that don't host a Hub are unaffected.

set -u
cd "$(dirname "$0")/.." || exit 0
PORT=8501
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG="$LOG_DIR/hub-streamlit.log"

PID="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -1)"
[ -z "$PID" ] && exit 0   # no Hub running here — nothing to bounce

# Only bounce if the listener is actually OUR dashboard, not some unrelated
# service that happens to hold :8501.
if ! ps -o command= -p "$PID" 2>/dev/null | grep -q "streamlit run automations/dashboard.py"; then
  exit 0
fi

echo "[$(date)] restart_hub: bouncing Hub pid $PID (code changed under a running server)" >> "$LOG"

kill "$PID" 2>/dev/null || true
for _ in 1 2 3 4 5 6; do
  sleep 1
  [ -z "$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)" ] && break
done
STILL="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)"
[ -n "$STILL" ] && { kill -9 $STILL 2>/dev/null || true; sleep 1; }

# Mirror the env launch_dashboard.command sets so subprocess.Popen / patchright
# don't crash post-fork on Sequoia and colorama doesn't re-enter on the signal
# handler (see the long comments in launch_dashboard.command).
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1

VENV_PY="./.venv/bin/python"
[ -x "$VENV_PY" ] || { echo "[$(date)] restart_hub: no venv python — cannot relaunch" >> "$LOG"; exit 0; }

# Detach fully (subshell + nohup) so the relaunched server outlives the git
# process / hook that invoked us. Mirror the launcher's final exec: arch -arm64
# on Apple Silicon so arm64-only wheels (_cffi_backend, etc.) load.
if [ "$(arch 2>/dev/null || echo unknown)" = "arm64" ]; then
  ( nohup /usr/bin/arch -arm64 "$VENV_PY" -m streamlit run automations/dashboard.py \
      --server.headless true --server.address 0.0.0.0 --server.port "$PORT" \
      --server.fileWatcherType=none >> "$LOG" 2>&1 & )
else
  ( nohup "$VENV_PY" -m streamlit run automations/dashboard.py \
      --server.headless true --server.address 0.0.0.0 --server.port "$PORT" \
      --server.fileWatcherType=none >> "$LOG" 2>&1 & )
fi

echo "[$(date)] restart_hub: relaunched Hub on :$PORT" >> "$LOG"
exit 0
