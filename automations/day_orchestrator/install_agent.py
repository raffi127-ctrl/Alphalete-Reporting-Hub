"""Install (or refresh) a committed LaunchAgent on THIS machine — the manual
scheduler-mini.md step, made runnable via `lucy rerun`.

WHY this exists as a runnable module (not just a mini_control action): the mini's
control poller is a long-lived `--loop` process, so a brand-new poller action
isn't live until the process restarts — and nothing in the running poller
restarts it. But `rerun` loads schedule_config fresh and runs the target as a
SUBPROCESS (fresh code from disk), so routing the install through a (non-
scheduled) registry entry lets a new LaunchAgent go live with just
`lucy update` + `lucy rerun install_<x>_agent` — no one at the mini.

What it does for `com.alphalete.<name>`:
  1. read deploy/com.alphalete.<name>.plist, rewrite the committed laptop path to
     THIS machine's repo path,
  2. write it to ~/Library/LaunchAgents/,
  3. make the referenced wrapper .sh executable,
  4. plutil -lint it,
  5. launchctl bootout (ignore if absent) + bootstrap into gui/<uid> — a clean,
     idempotent reload,
  6. verify with launchctl print.

Only ever touches com.alphalete.* agents shipped in this repo's deploy/ — never
an arbitrary plist. Read-only w.r.t. any Google Sheet / report data.

    python -m automations.day_orchestrator.install_agent je-sunday-catchup
"""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "/Users/megan/1st Claude Folder"   # committed laptop path in the plists


def install(name: str) -> tuple[bool, str]:
    name = name.strip().replace("com.alphalete.", "").replace(".plist", "")
    if not name or "/" in name or ".." in name:
        return False, f"bad launchagent name {name!r}"
    label = f"com.alphalete.{name}"
    src = REPO_ROOT / "deploy" / f"{label}.plist"
    if not src.exists():
        return False, f"{label}.plist not found in {src.parent} — git pull first?"

    fixed = src.read_text().replace(PLACEHOLDER, str(REPO_ROOT))
    la_dir = Path(os.path.expanduser("~/Library/LaunchAgents"))
    la_dir.mkdir(parents=True, exist_ok=True)
    dest = la_dir / f"{label}.plist"
    dest.write_text(fixed)

    # ensure the wrapper .sh is executable (git keeps 0755; belt + suspenders)
    try:
        for a in plistlib.loads(fixed.encode()).get("ProgramArguments", []):
            if isinstance(a, str) and a.endswith(".sh") and os.path.exists(a):
                os.chmod(a, os.stat(a).st_mode | stat.S_IXUSR | stat.S_IXGRP
                         | stat.S_IXOTH)
    except Exception:  # noqa: BLE001 — chmod is best-effort
        pass

    lint = subprocess.run(["plutil", "-lint", str(dest)],
                          capture_output=True, text=True, timeout=30)
    if lint.returncode != 0:
        return False, f"plutil lint failed: {(lint.stdout + lint.stderr).strip()[:160]}"

    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"

    def _loaded() -> bool:
        return subprocess.run(["launchctl", "print", target],
                              capture_output=True, text=True,
                              timeout=30).returncode == 0

    # `launchctl bootout` is ASYNCHRONOUS — it returns before the old job is fully
    # torn down. Bootstrapping immediately (as this used to) races: launchd still
    # sees the old job, the bootstrap silently no-ops, and the STALE schedule keeps
    # firing while we falsely report "loaded ✓" (it only checked the label exists).
    # That's the 2026-07-08 bug: the plist FILE said Hour 4, but launchd kept firing
    # the boot-time Hour 6 schedule for 15 days across repeated "successful" reloads.
    # Fix: bootout, then POLL until the job is genuinely gone, THEN bootstrap, and
    # fail LOUDLY (never a false ✓) if either step doesn't take.
    subprocess.run(["launchctl", "bootout", target],
                   capture_output=True, text=True, timeout=30)   # ignore if absent
    gone = False
    for _ in range(40):                     # up to ~10s for launchd to release it
        if not _loaded():
            gone = True
            break
        time.sleep(0.25)
    if not gone:
        return False, (f"{label}: old job STILL loaded 10s after bootout — launchd "
                       "won't release it (may need `launchctl remove` or a reboot); "
                       "reload aborted, schedule UNCHANGED")

    boot = subprocess.run(["launchctl", "bootstrap", domain, str(dest)],
                          capture_output=True, text=True, timeout=30)
    if boot.returncode != 0 or not _loaded():
        return False, (f"{label}: bootstrap failed (exit {boot.returncode}): "
                       f"{(boot.stdout + boot.stderr).strip()[:180]}")
    return True, (f"{label} reloaded in {domain} ✓ "
                  "(race-free: old job confirmed gone before bootstrap)")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m automations.day_orchestrator.install_agent <name>")
        return 2
    ok, msg = install(args[0])
    print(msg, flush=True)
    if ok:
        print("=== done ===", flush=True)   # clean-run sentinel for the poller
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
