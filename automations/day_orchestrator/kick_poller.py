"""One-shot: restart the mini-control poller so it reloads its own code.

Registered as an off-cadence report so `lucy rerun kick_poller` can restart the
poller REMOTELY via the (already-known) `rerun` action — `rerun` spawns a fresh
subprocess with the latest on-disk code, so this works even when the running
poller predates `restart_poller` / the git-HEAD self-reload (the bootstrap).

Detached + delayed: this process returns (so the poller writes the rerun result)
BEFORE `kickstart -k` SIGKILLs + relaunches the poller. start_new_session so the
kickstart child isn't in the poller's process group and survives the kill.
"""
import os
import subprocess
import sys

LABEL = "com.alphalete.mini-control"


def main() -> int:
    try:
        subprocess.Popen(
            ["/bin/sh", "-c",
             f"sleep 3; launchctl kickstart -k gui/{os.getuid()}/{LABEL}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't schedule kickstart: {e}")
        return 1
    print(f"scheduled kickstart of {LABEL} (~3s) — poller reloads its code")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
