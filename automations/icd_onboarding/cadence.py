"""How often the board's OwnerVille scan runs, in one place.

Megan, 2026-11-24: *"the Ownerville scan should run every 15 minutes, 8 to
noon, and then can go every 30 minutes, noon to 3, and then hourly, 3 to 8
a.m."*

WHY THE DAY IS SHAPED LIKE THAT. The scan's whole job is to notice that
somebody finished a quiz, signed a document or passed a check, and the hours
it matters in are the hours an orientation is running. A new start sits down at
8 and works through the morning, so that is when an answer can change in
minutes; by the afternoon what is left is waiting on other people, and
overnight nothing moves at all. So the clock follows the work rather than
being one interval chosen for the whole day.

IT IS NOT FREE, WHICH IS WHY IT IS BANDED AND NOT JUST "EVERY 15 MINUTES".
The OwnerVille half of the board run is 18 of its 22 page loads -- measured on
Raf's two funnels, 2026-11-22, which is why the NAMES were split onto their own
15-minute pass in the first place. Four reads an hour, all day, on forty office
machines is the cost this banding exists to avoid paying at 2am for an answer
nobody is waiting on.

ONE DEFINITION, TWO CALLERS. The Lucys reach it through the hourly agent's
wrapper and an office's own machine through `eco_job`; both ask `due`. A second
copy of these bands is how one of the two quietly keeps the old clock.

MACHINE-LOCAL, ON PURPOSE. "8 to noon" is 8 to noon where the orientation is
happening, so the comparison is against the local clock of the box doing the
reading -- which is the office's own machine once the step moves there.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence, Tuple

# (from_hour, until_hour, minutes between runs). Half-open: [from, until).
# The last band wraps midnight, which is why it is written as two.
BANDS: Sequence[Tuple[int, int, int]] = (
    (8, 12, 15),       # orientation morning -- an answer can change in minutes
    (12, 15, 30),      # afternoon -- mostly waiting on other people now
    (15, 24, 60),      # evening
    (0, 8, 60),        # overnight: nothing moves, but a 7am answer is ready by 8
)


def every_minutes(now: Optional[dt.datetime] = None) -> int:
    """How many minutes apart runs should be at this hour."""
    hour = (now or dt.datetime.now()).hour
    for start, until, minutes in BANDS:
        if start <= hour < until:
            return minutes
    # Unreachable while BANDS covers 0-24, and an hour with no band must not
    # mean "run constantly": the slowest band is the safe answer.
    return max(m for _s, _u, m in BANDS)


def due(last: Optional[dt.datetime] = None,
        now: Optional[dt.datetime] = None) -> bool:
    """Is a scan due? True when nothing has run yet.

    THE BAND OF *NOW*, not of the last run. A scan that last went at 7:50 is
    due at 8:05 because 8 o'clock is a 15-minute hour -- reading the band of
    the earlier run would hold the morning's first fast pass back to 8:50.
    """
    now = now or dt.datetime.now()
    if last is None:
        return True
    gap = (now - last).total_seconds() / 60.0
    # A clock that went backwards (a laptop waking, a DST shift) must not lock
    # the scan out until the gap goes positive again.
    if gap < 0:
        return True
    return gap >= every_minutes(now)


def plist_minutes() -> Sequence[Tuple[int, int]]:
    """(hour, minute) pairs for a launchd StartCalendarInterval that fires at
    least as often as the bands need.

    launchd has no "every N minutes within these hours", so the agent fires on
    the band's own minutes and the module decides. Generated rather than typed:
    a hand-written list of 60-odd entries is where a missing hour hides.
    """
    out = []
    for hour in range(24):
        step = every_minutes(dt.datetime(2000, 1, 1, hour))
        for minute in range(0, 60, step):
            out.append((hour, minute))
    return tuple(out)


# WHERE "WHEN DID IT LAST RUN" LIVES ON A LUCY. An office's own machine keeps
# it with the rest of its state (`eco_job.state_path`); a Lucy has no such
# file, and the launchd agent fires 39 times a day now, so without a stamp
# every fire would be a full pass.
def stamp_path():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[2] / "output" / "state"
            / "icd-onboarding-last.txt")


def last_run() -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(stamp_path().read_text().strip())
    except Exception:       # noqa: BLE001 -- no stamp is "never ran"
        return None


def mark_run(now: Optional[dt.datetime] = None) -> None:
    p = stamp_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((now or dt.datetime.now()).isoformat(timespec="seconds"))
    except OSError:         # noqa: BLE001 -- only costs an extra pass
        pass


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plist", action="store_true",
                    help="print the StartCalendarInterval rows for the agent")
    a = ap.parse_args(argv)
    if a.plist:
        for hour, minute in plist_minutes():
            print("        <dict><key>Hour</key><integer>%d</integer>"
                  "<key>Minute</key><integer>%d</integer></dict>" % (hour, minute))
        return 0
    now = dt.datetime.now()
    print("now        : %s" % now.isoformat(timespec="seconds"))
    print("this hour  : every %d minute(s)" % every_minutes(now))
    print("last run   : %s" % (last_run() or "never"))
    print("due now    : %s" % ("yes" if due(last_run(), now) else "no"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
