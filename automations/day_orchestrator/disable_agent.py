"""Disable (retire) a committed LaunchAgent on THIS machine — the inverse of
install_agent, made runnable via `lucy rerun`.

WHY a runnable module (not a poller action): same reason as install_agent — the
control poller is a long-lived process, so a brand-new action isn't live until
it restarts. `rerun` loads schedule_config fresh and runs the target as a
SUBPROCESS from disk, so this goes live with `lucy update` +
`lucy rerun disable_<x>_agent` and nobody at the machine.

Used to retire a standalone agent when its report moves into the 4am
orchestrator flow (2026-07-20: att_order_log). Without this, activating the
report in the flow while its standalone agent still fires = a DOUBLE run.

For com.alphalete.<name>:
  1. launchctl bootout from gui/<uid>, race-free: bootout is async, so POLL
     until the job is genuinely gone (same trap install_agent documents),
  2. move ~/Library/LaunchAgents/com.alphalete.<name>.plist aside to
     .plist.disabled so a re-login / LaunchAgents reload can't re-load it,
  3. confirm it's no longer loaded.

REVERSIBLE: `lucy rerun install_<name>_agent` re-creates the plist from deploy/
and bootstraps it (install_agent does bootout+bootstrap, no launchctl disable,
so nothing here blocks a re-install). Or move the .disabled file back by hand.

Only ever touches com.alphalete.* agents. Never runs, never `launchctl remove`s
(that can wedge launchd — see install_agent's 2026-07-10 note); read-only w.r.t.
any Google Sheet / report data.

    python -m automations.day_orchestrator.disable_agent att-order-log
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def disable(name: str) -> tuple[bool, str]:
    name = name.strip().replace("com.alphalete.", "").replace(".plist", "")
    if not name or "/" in name or ".." in name:
        return False, f"bad launchagent name {name!r}"
    label = f"com.alphalete.{name}"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"

    def _loaded() -> bool:
        return subprocess.run(["launchctl", "print", target],
                              capture_output=True, text=True,
                              timeout=30).returncode == 0

    was_loaded = _loaded()

    # bootout is ASYNCHRONOUS — it returns before launchd tears the job down.
    # Poll until it's genuinely gone and fail LOUDLY if it won't release, so we
    # never falsely report "disabled" while the old schedule keeps firing (the
    # mirror of install_agent's 2026-07-08 race).
    subprocess.run(["launchctl", "bootout", target],
                   capture_output=True, text=True, timeout=30)   # ignore if absent
    gone = False
    for _ in range(40):                     # up to ~10s for launchd to release it
        if not _loaded():
            gone = True
            break
        time.sleep(0.25)
    if not gone:
        return False, (f"{label}: STILL loaded 10s after bootout — launchd won't "
                       "release it (may need a reboot); NOT disabled, it may still "
                       "fire — leave the report OUT of the flow until this clears")

    # Move the installed plist aside so a re-login can't re-load it. Reversible:
    # install_<name>_agent rewrites it from deploy/, or move the .disabled back.
    la = Path(os.path.expanduser("~/Library/LaunchAgents")) / f"{label}.plist"
    if la.exists():
        aside = la.with_name(f"{label}.plist.disabled")
        try:
            if aside.exists():
                aside.unlink()
            la.rename(aside)
        except Exception as e:  # noqa: BLE001
            return True, (f"{label} booted out (was_loaded={was_loaded}) but could "
                          f"NOT stash the plist ({e}); a re-login could reload it — "
                          f"remove {la} by hand")
        return True, (f"{label} disabled ✓ (was_loaded={was_loaded}) — booted "
                      f"out + plist stashed as {aside.name}; re-enable with "
                      f"install_{name.replace('-', '_')}_agent")
    return True, (f"{label} disabled ✓ (was_loaded={was_loaded}) — booted out; "
                  "no installed plist in ~/Library/LaunchAgents to stash")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m automations.day_orchestrator.disable_agent <name>")
        return 2
    ok, msg = disable(args[0])
    print(msg, flush=True)
    if ok:
        print("=== done ===", flush=True)   # clean-run sentinel for the poller
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
