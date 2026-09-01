#!/bin/bash
# 3:15am AppStream self-heal — runs on Lucy 2, the sole AppStream holder
# (com.alphalete.appstream-selfheal).
#
# WHY (Megan 2026-08-31: "I'm not up at 3:30 which is why this can't be a manual
# thing all the dang time"). The rqst SSO token lives ~2h, nothing uses the
# console between midnight and 4am, and the holder's in-loop mint re-reads the
# SAME token off ownerville's warm page instead of getting a new one. So the
# token can die overnight and the 4am batch meets a dead session.
#
# A holder RESTART does mint, because it builds a fresh context. This checks
# first and only restarts when the session will not survive the batch, then
# pushes the new token to all three machines. It is SILENT when nothing was
# wrong; it alerts only when it could not recover.
#
# Manual:  bash deploy/appstream_selfheal.sh --check   (report only, changes nothing)

set -u

cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
mkdir -p output/logs

# macOS Sequoia fork-safety + proxy workarounds, mirroring the other wrappers.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

exec "$VENV_PY" -m automations.shared.appstream_selfheal "$@" \
    >> "output/logs/appstream-selfheal.log" 2>&1
