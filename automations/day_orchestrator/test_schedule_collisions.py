"""A LaunchAgent whose overlap guard can never win.

WHAT THIS GUARDS (2026-11-20). `com.alphalete.icd-onboarding-no-shows` was
installed to fire at 19:30. `com.alphalete.icd-onboarding` fires at :30 of
every hour from 6:30 to 20:30 and drives the same ApplicantStream profile, and
the no-shows wrapper skips itself when it sees that module already running.
So the walk met the board run on its FIRST fire and every fire after: it ran
on time at 19:30:05, skipped, wrote one line to a skip log on Lucy 3, and left
no heartbeat. Installed, scheduled, correct in every part, and never once
doing its job.

The overlap guard was not the bug -- it did exactly what it should. Setting
two jobs that exclude each other to the same minute was. Nothing caught it
because nothing compared the two schedules; the only evidence was an absent
heartbeat, which reads the same as a job nobody installed.

    PYTHONPATH=. .venv/bin/python -m unittest \
        automations.day_orchestrator.test_schedule_collisions
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from automations.day_orchestrator import schedule_guard as SG

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

# `pgrep -f "automations.icd_onboarding.run"` in a wrapper = "I refuse to run
# beside this module". The quotes are optional in shell, so they are here too.
_GUARD = re.compile(r"""pgrep\s+-f\s+["']?(automations[\w.]+)""")
# `-m automations.x.y` = "this wrapper IS that module".
_RUNS = re.compile(r"-m\s+(automations[\w.]+)")


def _fire_minutes(plist: Path):
    """Every (weekday, hour, minute) this plist fires at, or None if untimed.

    WEEKDAY IS PART OF THE KEY. Without it two jobs that both fire at 19:00 --
    one on Mondays, one on Fridays -- read as a clash and the check cries wolf
    until somebody turns it off. `None` is the wildcard launchd means by an
    entry with no Weekday: every day, so it clashes with any weekday.
    """
    sched = SG._timed_schedule(plist)
    if not sched:
        return None
    out = set()
    for entry in (sched if isinstance(sched, list) else [sched]):
        if not isinstance(entry, dict) or "Hour" not in entry:
            continue
        wd = entry.get("Weekday")
        out.add((None if wd is None else int(wd),
                 int(entry["Hour"]), int(entry.get("Minute", 0))))
    return out or None


def _overlap(mine, theirs):
    """Fire times the two share, honouring the every-day wildcard."""
    hit = set()
    for wd_a, h, m in mine:
        for wd_b, h2, m2 in theirs:
            if (h, m) != (h2, m2):
                continue
            if wd_a is None or wd_b is None or wd_a == wd_b:
                hit.add((wd_a if wd_b is None else wd_b, h, m))
    return hit


def _wrapper_of(plist: Path):
    d = SG._load_plist(plist) or {}
    for arg in d.get("ProgramArguments") or []:
        if str(arg).endswith(".sh"):
            return DEPLOY / Path(str(arg)).name
    return None


def _jobs():
    """[(plist, wrapper text, modules it runs, modules it refuses to overlap)]"""
    out = []
    for plist in sorted(DEPLOY.glob("*.plist")):
        wrapper = _wrapper_of(plist)
        if wrapper is None or not wrapper.exists():
            continue
        text = wrapper.read_text(errors="replace")
        out.append((plist, set(_RUNS.findall(text)),
                    set(_GUARD.findall(text)), _fire_minutes(plist)))
    return out


_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _say(fire):
    wd, h, m = fire
    day = "every day" if wd is None else _DAYS[wd % 7]
    return "%s %02d:%02d" % (day, h, m)


# No known clashes. An entry here is a bug with a name, not permission, and
# the b2b pair that was listed on 2026-11-20 is fixed rather than excused.
# test_every_known_clash_is_still_a_real_clash below fails on any entry that
# has quietly stopped being one, so this cannot rot back into a waiver list.
_KNOWN_CLASHES = set()


class GuardedJobsDoNotShareAFireTime(unittest.TestCase):

    def test_no_job_fires_at_the_same_minute_as_one_it_refuses_to_overlap(self):
        jobs = _jobs()
        self.assertTrue(jobs, "no deploy plists found -- the scan is broken")
        clashes = []
        for plist, _runs, refuses, mine in jobs:
            if not refuses or not mine:
                continue
            for other, other_runs, _r2, theirs in jobs:
                if other == plist or not theirs:
                    continue
                if not (refuses & other_runs):
                    continue
                shared = _overlap(mine, theirs)
                if shared and frozenset({plist.name, other.name}) not in _KNOWN_CLASHES:
                    clashes.append(
                        "%s fires at %s with %s, which it refuses to run beside"
                        % (plist.name,
                           ", ".join(_say(f) for f in sorted(
                               shared, key=lambda f: (f[0] is not None, f))),
                           other.name))
        self.assertEqual(clashes, [], "\n" + "\n".join(clashes))

    def test_the_no_shows_walk_is_off_the_board_runs_half_hour(self):
        """The original bug, pinned by name: both were on :30."""
        walk = _fire_minutes(DEPLOY / "com.alphalete.icd-onboarding-no-shows.plist")
        board = _fire_minutes(DEPLOY / "com.alphalete.icd-onboarding.plist")
        self.assertTrue(walk and board)
        self.assertFalse(_overlap(walk, board),
                         "the walk is back on a minute the board run owns")

    def test_every_known_clash_is_still_a_real_clash(self):
        """An exception that has quietly fixed itself must not linger here."""
        jobs = {p.name: (runs, refuses, mins) for p, runs, refuses, mins in _jobs()}
        for pair in _KNOWN_CLASHES:
            a, b = sorted(pair)
            self.assertIn(a, jobs, "%s is gone; drop it from _KNOWN_CLASHES" % a)
            self.assertIn(b, jobs, "%s is gone; drop it from _KNOWN_CLASHES" % b)
            (runs_a, ref_a, min_a), (runs_b, ref_b, min_b) = jobs[a], jobs[b]
            self.assertTrue(
                (ref_a & runs_b) or (ref_b & runs_a),
                "%s and %s no longer refuse each other; drop the exception" % (a, b))
            self.assertTrue(
                _overlap(min_a or set(), min_b or set()),
                "%s and %s no longer share a fire time; drop the exception" % (a, b))

    def test_the_b2b_final_stays_an_hour_off_its_hourly(self):
        """Sat 16:00 for both, fixed 2026-11-20. The shape, not just the minute:
        gaps ends, the hourly posts 30 min later, the final an hour after that.
        """
        final = _fire_minutes(DEPLOY / "com.alphalete.b2b-dispositions-final.plist")
        hourly = _fire_minutes(DEPLOY / "com.alphalete.b2b-dispositions-hourly.plist")
        self.assertTrue(final and hourly)
        self.assertFalse(_overlap(final, hourly),
                         "the b2b final is back on a minute the hourly owns")
        by_day = {wd: (h, m) for wd, h, m in hourly}
        for wd, h, m in final:
            self.assertIn(wd, by_day, "a final with no hourly that day")
            hh, hm = by_day[wd]
            self.assertEqual((h * 60 + m) - (hh * 60 + hm), 60,
                             "day %s: the final should be 1h after the hourly"
                             % wd)

    def test_the_scan_can_actually_see_the_pair(self):
        """A test that silently matches nothing would pass forever."""
        names = {p.name for p, _r, refuses, _m in _jobs() if refuses}
        self.assertIn("com.alphalete.icd-onboarding-no-shows.plist", names)
