#!/bin/bash
# Hourly AppStream session renewal (com.alphalete.appstream-autorenew).
#
# WHY (Megan 2026-09-01, after her third login before noon: "this CANNOT keep
# happening" / "it cost us a whole day"). The rqst token lives ~2h and nothing
# renewed it, so a person re-seeded it every two hours.
#
# MEASURED that day: re-capturing against a profile whose session is still ALIVE
# completes unattended in under a minute. The human is only needed once the
# profile has gone COLD — and it goes cold because we wait for the token to die
# before trying. So renew at 75 minutes instead of at death.
#
# ONE MACHINE ONLY. The other runners authenticate from the pushed
# storage_state, not a browser session, so they never need a seeded profile —
# this renews and pushes to all three.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
exec .venv/bin/python -m automations.shared.appstream_autorenew "$@" \
    >> "output/logs/appstream-autorenew.log" 2>&1
