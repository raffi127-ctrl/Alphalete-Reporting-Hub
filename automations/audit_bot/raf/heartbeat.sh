#!/bin/bash
# Wrapper launchd calls every 5 minutes. Activates the venv + runs heartbeat.py.
set -e
RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUNTIME_DIR"
source venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}
exec python heartbeat.py
