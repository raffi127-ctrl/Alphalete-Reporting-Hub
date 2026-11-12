"""One-shot: from a Lucy on the office LAN, restart ANOTHER Lucy's queue reader.

WHY (2026-10-20). Lucy 1's Mini Control queue went silent at 17:56 while the
machine kept running its scheduled reports. The fix is two `launchctl
kickstart` lines on Lucy 1 -- but the queue that would carry them is the dead
thing, and the laptop working the channel was off the office network. Lucy 3's
queue was alive and Lucy 3 sits on the same LAN, so this lets `lucy rerun
kick_lucy1_queue` (routed to Lucy 3) do it over SSH.

Read-only on everything but the target's two LaunchAgents. Fails fast and says
why if this box has no SSH key for the target (BatchMode, short timeout).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

TARGETS = {
    "lucy1": ("alphalete", ("Alphaletes-Mac-mini.local",)),
    # 2026-11-12: Lucy 3's queue went silent at 21:17 while the box stayed up
    # on the LAN (peer_probe from Lucy 1: ping + :22 answer). Same fix, run
    # from Lucy 1 as `lucy rerun kick_lucy3_queue`.
    "lucy3": ("lucy3", ("Lucys-Mac-mini.local",)),
}
CMD = ("launchctl kickstart -k gui/$(id -u)/com.alphalete.mini-control; "
       "launchctl kickstart -k gui/$(id -u)/com.alphalete.mini-control-read "
       "2>/dev/null; "
       "launchctl kickstart -k gui/$(id -u)/com.alphalete.mini-control-text "
       "2>/dev/null; echo KICKED; launchctl list | grep mini-control; "
       # A wedged box (slow ping) usually has one process eating it -- show
       # the top few so the kick's log says what to look at next.
       "echo '--- top cpu/mem ---'; "
       "ps -Ao pid,%cpu,%mem,etime,comm -r | head -6; "
       "vm_stat | egrep 'free|Swap' ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", default="lucy1", choices=sorted(TARGETS))
    a = ap.parse_args(argv)
    user, hosts = TARGETS[a.target]
    for host in hosts:
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-o", "StrictHostKeyChecking=accept-new",
                 "%s@%s" % (user, host), CMD],
                capture_output=True, text=True, timeout=40)
        except Exception as e:  # noqa: BLE001
            print("%s: could not run ssh (%s)" % (host, type(e).__name__))
            continue
        out = (r.stdout + r.stderr).strip()
        print("%s: rc=%s\n%s" % (host, r.returncode, out[-600:]))
        if r.returncode == 0 and "KICKED" in r.stdout:
            print("=== done ===")
            return 0
    print("could not reach %s from this machine -- someone at it must run the "
          "kickstart lines" % a.target)
    return 1


if __name__ == "__main__":
    sys.exit(main())
