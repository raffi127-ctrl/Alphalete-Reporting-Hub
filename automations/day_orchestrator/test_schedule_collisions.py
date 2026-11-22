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

import json
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


CONFIG = (Path(__file__).resolve().parent / "schedule_config.json")


def _retired_labels() -> set:
    """Plists that exist in deploy/ but are installed NOWHERE.

    `install_agent` is the only thing that loads these, and every job it can
    run is a `reports` entry whose base_args start with the plist's label.
    A label that has a `--remove` entry and NO install entry is retired: the
    file is kept so `--remove` still has something to unload, and so the next
    person can read why it went away.

    A RETIRED PLIST CANNOT CLASH WITH ANYTHING. Scanning it anyway is how
    this check reported a Saturday collision between b2b-dispositions-final
    (retired 2026-09-29) and b2b-dispositions-hourly that no machine has run
    since September -- and nearly got the LIVE job moved to "fix" it.

    Plists with neither entry stay in scope: something else may install them,
    and guessing them retired would make this check quietly blind.
    """
    reports = (json.loads(CONFIG.read_text()).get("reports") or {})
    installs, removes = set(), set()
    for job in reports.values():
        if not isinstance(job, dict):
            continue
        if job.get("command") != ["automations.day_orchestrator.install_agent"]:
            continue
        args = job.get("base_args") or []
        if not args:
            continue
        (removes if "--remove" in args else installs).add(args[0])
    return removes - installs


def _label_of(plist: Path) -> str:
    return plist.name[len("com.alphalete."):-len(".plist")]


def _jobs():
    """[(plist, wrapper text, modules it runs, modules it refuses to overlap)]"""
    out = []
    retired = _retired_labels()
    for plist in sorted(DEPLOY.glob("*.plist")):
        if _label_of(plist) in retired:
            continue
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


# Empty, and the story of why it is empty is worth more than the entry was.
#
# This check first reported b2b-dispositions-final and b2b-dispositions-hourly
# both firing Sat 16:00 through a wrapper that skips itself. Two attempts were
# made on 2026-11-20 to "fix" that, and BOTH were wrong:
#
#   1. Move the final to 17:00. It broke Carlos's explicit request (8/6,
#      commit b8b89e6) that Saturday's last message land at 4pm. Reverted.
#   2. Move the hourly earlier. Worse -- see below.
#
# There was never a clash. b2b-dispositions-final was RETIRED on 2026-09-29
# when Carlos moved everything to one post, and `remove_b2b_dispositions_final_agent`
# took it off Lucy 2. The plist stays in deploy/ so that removal still has a
# file to unload, but nothing installs it. The scan was reading a dead file.
#
# Which makes the Saturday hourly at 16:00 the ONE message Carlos asked for by
# name -- it IS the 4pm close, not a stray run in front of it. Moving it earlier
# would have broken the exact request that reverting #1 restored, in the same
# session, from the opposite direction.
#
# THE LESSON, because it cost two wrong changes: a plist in deploy/ is not a
# running job. Check whether anything installs it before reading its schedule
# as fact. _retired_labels() now does that, which is why this set is empty.
#
# An entry here would be a bug with a name, not permission.
# test_every_known_clash_is_still_a_real_clash fails on any entry that has
# quietly stopped being one, so this cannot rot into a waiver list.
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

    def test_the_scan_can_actually_see_the_pair(self):
        """A test that silently matches nothing would pass forever."""
        names = {p.name for p, _r, refuses, _m in _jobs() if refuses}
        self.assertIn("com.alphalete.icd-onboarding-no-shows.plist", names)


class RetiredPlistsAreNotRunningJobs(unittest.TestCase):

    def test_the_retired_final_is_out_of_scope(self):
        """The dead file that nearly got the live job moved."""
        self.assertIn("b2b-dispositions-final", _retired_labels(),
                      "b2b-dispositions-final has an install entry again -- "
                      "if it is live, its Saturday 16:00 really does clash "
                      "with the hourly and one of them needs to move")
        scanned = {p.name for p, _r, _g, _m in _jobs()}
        self.assertNotIn("com.alphalete.b2b-dispositions-final.plist", scanned)

    def test_a_live_plist_is_still_in_scope(self):
        """The retired filter must not swallow jobs that do run."""
        scanned = {p.name for p, _r, _g, _m in _jobs()}
        self.assertIn("com.alphalete.b2b-dispositions-hourly.plist", scanned)

    def test_saturday_hourly_is_carloss_4pm_close(self):
        """DO NOT MOVE THIS. Carlos asked for 4pm by name (commit b8b89e6).

        With the final retired, the hourly's Sat 16:00 is the last B2B message
        of the day. Twice on 2026-11-20 a schedule tidy-up tried to move one
        end of this or the other; this test is the stop.
        """
        fires = _fire_minutes(DEPLOY / "com.alphalete.b2b-dispositions-hourly.plist")
        self.assertIn((6, 16, 0), fires,
                      "Saturday's B2B close moved off 16:00 -- Carlos asked "
                      "for 4pm by name; put it back")


class WhatWeSayTheClockIs(unittest.TestCase):
    """The no-show walk's documented time must be the time it fires.

    THE DRIFT THIS CATCHES IS NOT COSMETIC. ff1f506 moved this walk off 19:30
    because that minute belongs to the hourly board run, and the walk had
    never once completed a pass. The plist moved; six strings about it did not
    -- its own header, its wrapper's header, its schedule_config note, its
    install handle's note, and BOTH display_names, which is the name on the
    Hub. For two days every written description of the job said 19:30 while it
    ran at 21:15, so anybody reading the repo to find out why it was quiet was
    sent to the wrong hour (found 2026-11-22).

    PINNED BY NAME, not swept for. A general version of this check was written
    first and produced eleven findings, all but one a false alarm: one wrapper
    serves several plists at different times (digi_docs.sh, new_start_followup
    .sh), and a wrapper legitimately names times that are not its own -- this
    walk's own comment cites Blue Ink's 7:30am, which is the whole reason the
    evening matters. Telling "the schedule" from "a time this job cares about"
    needs a convention the repo does not have, and a check that cries wolf
    eleven times is one somebody turns off. Same judgement as the clash
    exceptions above: pin the thing that actually broke.
    """

    # 19:30 -> "19:30" and "7:30pm". Both spellings are used in this repo.
    def _spellings(self, hour: int, minute: int):
        ampm = "am" if hour < 12 else "pm"
        h12 = hour % 12 or 12
        return {"%d:%02d" % (hour, minute), "%d:%02d%s" % (h12, minute, ampm)}

    def _written_times(self, text: str):
        """Every clock time the text states, in the two spellings above."""
        found = set()
        for h, m in re.findall(r"\b(\d{1,2}):(\d{2})\b(?!\s*[ap]m)", text):
            found.add("%d:%02d" % (int(h), int(m)))
        for h, m, ap in re.findall(r"\b(\d{1,2}):(\d{2})\s*([ap])m\b", text,
                                   re.I):
            found.add("%d:%02d%sm" % (int(h), int(m), ap.lower()))
        return found

    def test_every_place_the_walk_is_described_says_21_15(self):
        """All six strings that drifted, plus the plist they drifted from.

        Each is asked to STATE the right time, not merely to avoid the wrong
        one: these texts cite other jobs' clocks on purpose, so "mentions no
        other time" would be false, while "never says its own" is exactly the
        hole that let 19:30 stand for two days.
        """
        plist = DEPLOY / "com.alphalete.icd-onboarding-no-shows.plist"
        fire = _fire_minutes(plist)
        self.assertEqual(len(fire or []), 1, "this walk fires once a day")
        _wd, hour, minute = next(iter(fire))
        self.assertEqual((hour, minute), (21, 15),
                         "moved again? then move these strings with it")
        right = self._spellings(hour, minute)

        import json
        cfg = json.loads((Path(__file__).resolve().parent
                          / "schedule_config.json").read_text())["reports"]
        walk = cfg["icd_onboarding_no_shows"]
        inst = cfg["install_icd_onboarding_no_shows_agent"]
        wrapper = _wrapper_of(plist)
        where = {
            "the plist's own header": plist.read_text(errors="replace"),
            "the wrapper's header": wrapper.read_text(errors="replace"),
            "the walk's display_name": walk["display_name"],
            "the walk's _note": walk["_note"],
            "the walk's weekdays note": walk["_standalone_weekdays_note"],
            "the install handle's display_name": inst["display_name"],
            "the install handle's note": inst["_off_scheduler_note"],
        }
        missing = [name for name, text in where.items()
                   if not (self._written_times(text) & right)]
        self.assertEqual(
            missing, [],
            "fires at 21:15 but never says so in: %s" % ", ".join(missing))
