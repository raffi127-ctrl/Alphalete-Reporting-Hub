"""Stop + remove a committed LaunchAgent from THIS machine — the retirement
counterpart to install_agent, made runnable via `lucy rerun` so a scheduled job
on the mini can be turned off with no one at the mini.

WHY a runnable module (not a mini_control action): same reason as install_agent
— the poller is a long-lived `--loop` process, so a brand-new action isn't live
until it restarts, but `rerun` loads schedule_config fresh and runs the target
as a SUBPROCESS (fresh code from disk). So a `com.alphalete.*` job is stopped
with just `lucy update` + `lucy rerun uninstall_<x>_agent` — no mini visit.

What it does for `com.alphalete.<name>`:
  1. launchctl bootout gui/<uid>/com.alphalete.<name>  (ignore if already gone),
  2. delete ~/Library/LaunchAgents/com.alphalete.<name>.plist if present,
  3. verify with launchctl print that it's NO LONGER registered.

Only ever touches com.alphalete.* agents (same guard as install_agent) — never
an arbitrary label. Read-only w.r.t. any Google Sheet / report data. Idempotent:
a second run on an already-removed agent is a clean success.

    python -m automations.day_orchestrator.uninstall_agent first-last-sale-mon
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def uninstall(name: str) -> tuple[bool, str]:
    name = name.strip().replace("com.alphalete.", "").replace(".plist", "")
    if not name or "/" in name or ".." in name:
        return False, f"bad launchagent name {name!r}"
    label = f"com.alphalete.{name}"
    domain = f"gui/{os.getuid()}"

    # 1. bootout — stop it + unregister. Non-zero when it wasn't loaded, which is
    #    fine (idempotent); we only care that it's gone by the end.
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                   capture_output=True, text=True, timeout=30)

    # 2. remove the plist so it can't be re-bootstrapped at next login.
    dest = Path(os.path.expanduser("~/Library/LaunchAgents")) / f"{label}.plist"
    removed = False
    if dest.exists():
        try:
            dest.unlink()
            removed = True
        except Exception as e:  # noqa: BLE001
            return False, f"bootout ok but couldn't delete {dest.name}: {str(e)[:120]}"

    # 3. verify it's no longer registered — a non-zero print means it's gone.
    chk = subprocess.run(["launchctl", "print", f"{domain}/{label}"],
                         capture_output=True, text=True, timeout=30)
    if chk.returncode == 0:
        return False, (f"{label} STILL registered after bootout — "
                       "another loader (login item?) may be reviving it")
    plist_note = "plist removed" if removed else "no plist on disk"
    return True, f"{label} stopped + unregistered in {domain} ✓ ({plist_note})"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m automations.day_orchestrator.uninstall_agent <name>")
        return 2
    ok, msg = uninstall(args[0])
    print(msg, flush=True)
    if ok:
        print("=== done ===", flush=True)   # clean-run sentinel for the poller
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
