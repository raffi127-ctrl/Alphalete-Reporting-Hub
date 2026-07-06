"""Set the mini's DAILY WAKE schedule so the 4am day-orchestrator isn't deferred
to ~6am (the mini deep-sleeps overnight, so launchd's 4am StartCalendarInterval
job only fires when the mini wakes). A scheduled wake at 03:55 brings it up in
time. Run on the mini via:  lucy rerun set_wake

pmset scheduling needs root, so this uses `sudo -n` (non-interactive — fails fast
if passwordless sudo isn't configured, instead of hanging on a password prompt).
Idempotent (pmset repeat replaces the prior schedule). Reversible on the mini with
`sudo pmset repeat cancel`. Prints the resulting schedule so we can confirm it took.
"""
from __future__ import annotations

import subprocess

WAKE_DAYS = "MTWRFSU"     # every day
WAKE_TIME = "03:55:00"    # 5 min before the 4:00 orchestrator


def _run(cmd, timeout=25):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    rc, out = _run(["sudo", "-n", "pmset", "repeat", "wakeorpoweron",
                    WAKE_DAYS, WAKE_TIME])
    if rc != 0:
        print(f"SET-WAKE FAILED (rc={rc}): {out[:170]} :: needs passwordless "
              f"sudo for pmset on the mini (add a NOPASSWD sudoers line) or run "
              f"`sudo pmset repeat wakeorpoweron {WAKE_DAYS} {WAKE_TIME}` by hand.")
        return
    _, sched = _run(["pmset", "-g", "sched"])       # read-only, no sudo
    print(f"SET-WAKE OK (wake {WAKE_DAYS} {WAKE_TIME}) :: {sched.strip()[:190]}")


if __name__ == "__main__":
    main()
