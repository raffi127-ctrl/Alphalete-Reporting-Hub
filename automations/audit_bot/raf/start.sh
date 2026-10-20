#!/bin/bash
# Starts the audit watcher in the background.
# Logs to .runtime/watcher.log. PID written to .runtime/watcher.pid.

set -e

RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUNTIME_DIR"

# Check if already running
if [[ -f watcher.pid ]] && kill -0 "$(cat watcher.pid)" 2>/dev/null; then
    echo "Watcher already running (PID $(cat watcher.pid))."
    echo "Tail the log:  tail -f \"$RUNTIME_DIR/watcher.log\""
    echo "Stop it:       \"$RUNTIME_DIR/stop.sh\""
    exit 0
fi

# Activate venv + launch
source venv/bin/activate
# WeasyPrint needs Homebrew libs (libgobject, libpango, etc.) on macOS
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}

# Main audit watcher (audio interviews)
nohup python audit.py --watch > watcher.log 2>&1 &
echo $! > watcher.pid

# Feedback watcher (Rafael's voice memos → transcripts)
nohup python feedback_watcher.py --watch > feedback_watcher.log 2>&1 &
echo $! > feedback_watcher.pid

# Slack watcher (reps upload audio in Slack → PDFs come back in thread)
nohup python slack_watcher.py > slack_watcher.log 2>&1 &
echo $! > slack_watcher.pid

sleep 1
if kill -0 "$(cat watcher.pid)" 2>/dev/null; then
    echo "Audit watcher started (PID $(cat watcher.pid))."
    echo "Drop audio files in:        ~/Documents/2nd-rd-audits/inbox/"
    echo "Reports appear in:          ~/Documents/2nd-rd-audits/reports/"
else
    echo "Audit watcher failed to start. Check $RUNTIME_DIR/watcher.log"
fi
if kill -0 "$(cat feedback_watcher.pid)" 2>/dev/null; then
    echo "Feedback watcher started (PID $(cat feedback_watcher.pid))."
    echo "Drop voice memos in:        ~/Documents/2nd-rd-audits/feedback_inbox/"
    echo "Transcripts appear in:      ~/Documents/2nd-rd-audits/feedback/"
else
    echo "Feedback watcher failed to start. Check $RUNTIME_DIR/feedback_watcher.log"
fi
if kill -0 "$(cat slack_watcher.pid)" 2>/dev/null; then
    echo "Slack watcher started (PID $(cat slack_watcher.pid))."
    echo "Slack bot listening — reps can upload audio to any channel it's in."
else
    echo "Slack watcher failed to start. Check $RUNTIME_DIR/slack_watcher.log"
fi
echo "Tail audit log:               tail -f \"$RUNTIME_DIR/watcher.log\""
echo "Tail feedback log:            tail -f \"$RUNTIME_DIR/feedback_watcher.log\""
echo "Tail slack log:               tail -f \"$RUNTIME_DIR/slack_watcher.log\""
echo "Stop all:                     \"$RUNTIME_DIR/stop.sh\""
