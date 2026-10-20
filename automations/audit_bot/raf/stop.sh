#!/bin/bash
# Stops the audit watcher.

set -e
RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUNTIME_DIR"

stopped_any=false

# Audit watcher
if [[ -f watcher.pid ]]; then
    PID="$(cat watcher.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Audit watcher stopped (PID $PID)."
        stopped_any=true
    fi
    rm -f watcher.pid
fi

# Feedback watcher
if [[ -f feedback_watcher.pid ]]; then
    PID="$(cat feedback_watcher.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Feedback watcher stopped (PID $PID)."
        stopped_any=true
    fi
    rm -f feedback_watcher.pid
fi

# Slack watcher
if [[ -f slack_watcher.pid ]]; then
    PID="$(cat slack_watcher.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "Slack watcher stopped (PID $PID)."
        stopped_any=true
    fi
    rm -f slack_watcher.pid
fi

if ! $stopped_any; then
    echo "Nothing was running."
fi
