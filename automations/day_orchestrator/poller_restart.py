"""Bounce the mini's lucy poller (com.alphalete.mini-control) so it reloads new
code — the missing piece for fully-remote deploys.

The gap: `lucy update` git-pulls new code, but the long-running poll process
keeps the OLD modules in memory, so a newly-added lucy action (e.g.
install_launchagent) reads as 'unknown action' until the poller restarts. And
the poller can't be restarted through the queue because the OLD poller doesn't
know a 'restart' action.

The escape hatch: `lucy rerun restart_poller` — rerun spawns THIS as a FRESH
subprocess (current on-disk code, not the poller's stale memory). It schedules a
DETACHED, DELAYED kickstart of the poller's launchd job. The delay lets the
current queue row finish + write its result before the poller is bounced (so the
row doesn't get stuck 'running' or re-processed); KeepAlive=true + the -k restart
bring the poller back within ~30s running the new code.

After it comes back, queue the new action (e.g. `lucy install_launchagent …`) —
the fresh poller now recognizes it.
"""
from __future__ import annotations

import os
import subprocess
import sys

LABEL = "com.alphalete.mini-control"
DELAY_S = 12


def main() -> int:
    uid = os.getuid()
    # Detached (start_new_session) so the kickstart survives the poller being
    # killed; delayed so the poller writes THIS action's queue result first.
    subprocess.Popen(
        ["bash", "-c", f"sleep {DELAY_S}; launchctl kickstart -k gui/{uid}/{LABEL}"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"scheduled poller restart (kickstart {LABEL}) in ~{DELAY_S}s — "
          "it reloads new code on relaunch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
