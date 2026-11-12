"""Fast mouse + right-click on THIS Mac (Megan, 2026-11-11: "we need the
right click on mouse thing and fast mouse on the Lucy's").

The same four settings the laptop walkthrough sets (Laptop-Setup-Mac.command,
"Mouse and screen"), as a job a Lucy can run from the queue:

    lucy --machine "Lucy 2" rerun mouse_prefs
    lucy --machine "Lucy 2" rerun mouse_prefs -- --dry-run   # just report

* fastest tracking speed for a mouse and a trackpad
* the right side of an Apple mouse = right-click (a normal two-button mouse
  already right-clicks; this is for Magic Mouse)

macOS reads these at login, so they take effect the next time the Lucy
restarts or logs in. Nothing here restarts it. Mac only; on Windows it says
so and changes nothing.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys

# (domain, key, type, value). "-g" = the global domain.
SETTINGS = (
    ("-g", "com.apple.mouse.scaling", "-float", "3"),
    ("-g", "com.apple.trackpad.scaling", "-float", "3"),
    ("com.apple.AppleMultitouchMouse", "MouseButtonMode", "-string", "TwoButton"),
    ("com.apple.driver.AppleBluetoothMultitouch.mouse", "MouseButtonMode", "-string", "TwoButton"),
)
LABEL = {
    "com.apple.mouse.scaling": "mouse speed",
    "com.apple.trackpad.scaling": "trackpad speed",
    "MouseButtonMode": "right-click",
}


def _read(domain: str, key: str) -> str:
    r = subprocess.run(["defaults", "read", domain, key],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "(not set)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="show what is set now and what would change")
    a = ap.parse_args(argv)
    if platform.system() != "Darwin":
        print("mouse_prefs: Mac only, nothing changed on %s" % platform.system())
        return 0
    host = platform.node()
    changed = 0
    for domain, key, typ, value in SETTINGS:
        before = _read(domain, key)
        same = before == value or (typ == "-float" and _same_float(before, value))
        what = "%s (%s)" % (LABEL.get(key, key), domain)
        if same:
            print("  already set   %-55s %s" % (what, before))
            continue
        if a.dry_run:
            print("  would set     %-55s %s -> %s" % (what, before, value))
            continue
        r = subprocess.run(["defaults", "write", domain, key, typ, value],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("  FAILED        %-55s %s" % (what, r.stderr.strip()[:120]))
            return 1
        print("  set           %-55s %s -> %s" % (what, before, value))
        changed += 1
    tail = " (takes effect at the next restart/login)" if changed else ""
    print("mouse_prefs on %s: %d changed%s%s" % (
        host, changed, " [dry run]" if a.dry_run else "", tail))
    return 0


def _same_float(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
