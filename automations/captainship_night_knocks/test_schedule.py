"""The clock rules, pinned. No network, no browser, no Sheet.

The first test is Raf's own example, in his own numbers — it is the thing that
was actually agreed in #l10-alphalete on 2026-09-07, so it is the thing that
must not drift.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from automations.captainship_night_knocks import schedule as S
from automations.captainship_night_knocks import zones as Z

CT = ZoneInfo("America/Chicago")

# A captainship shaped like the one Raf described: an office in Florida, one in
# Texas, one in California.
ROSTER = {"demo": ["Flo Rida", "Tex Ann", "Cal Ifornia"]}
FAKE_ZONES = {
    "flo rida":    "America/New_York",
    "tex ann":     "America/Chicago",
    "cal ifornia": "America/Los_Angeles",
}


def at_central(y, m, d, hh, mm=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=CT).astimezone(dt.timezone.utc)


def replay(roster, day=(2026, 9, 7), hours=range(17, 24)) -> dict:
    """{hour: [Due, ...]} for a night played tick by tick, the way run.tick
    does — each hour sees the markers the hours before it already sent.

    Passing `done` is not a detail of the test, it is the contract:
    GRACE_MIN is an hour (a wave still owed at 9:40 because Lucy 3 was busy
    must still go out), so "what fires at 9 PM" is only a well-formed question
    about a night whose 8 PM wave has already gone. An UNSENT wave staying due
    is the recovery this module is built for — `still_owed_an_hour_later`
    below is that case, asserted on purpose.
    """
    done, fired = set(), {}
    for hh in hours:
        got = S.due(at_central(day[0], day[1], day[2], hh), roster, done=done)
        fired[hh] = got
        done |= {d.marker for d in got}
    return fired


class RafsExample(unittest.TestCase):
    """8 CEN Florida -> 9 CEN Texas -> 11 CEN California, same night."""

    def setUp(self):
        p = mock.patch.dict(Z._BY_NORM, FAKE_ZONES, clear=False)
        p.start()
        self.addCleanup(p.stop)

    def _one(self, hh):
        # Monday 2026-09-07 is Labor Day but a working weekday for us (Mon-Sat).
        return replay(ROSTER)[hh]

    def test_eight_central_is_the_florida_wave(self):
        got = self._one(20)
        self.assertEqual([d.label for d in got], ["Eastern"])
        self.assertEqual(list(got[0].icds), ["Flo Rida"])

    def test_nine_central_is_the_texas_wave(self):
        got = self._one(21)
        self.assertEqual([d.label for d in got], ["Central"])
        self.assertEqual(list(got[0].icds), ["Tex Ann"])

    def test_eleven_central_is_the_california_wave(self):
        got = self._one(23)
        self.assertEqual([d.label for d in got], ["Pacific"])
        self.assertEqual(list(got[0].icds), ["Cal Ifornia"])

    def test_ten_central_fires_nothing_for_this_captainship(self):
        """No Mountain ICD here, so the 10 PM hour is silent — an empty wave is
        skipped, never mailed blank."""
        self.assertEqual(self._one(22), [])

    def test_each_wave_carries_only_that_wave(self):
        """The whole point: nobody appears before they finished knocking."""
        for hh, who in ((20, "Flo Rida"), (21, "Tex Ann"), (23, "Cal Ifornia")):
            got = self._one(hh)
            self.assertEqual(list(got[0].icds), [who], f"at {hh}:00 CT")


class Idempotency(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(Z._BY_NORM, FAKE_ZONES, clear=False)
        p.start()
        self.addCleanup(p.stop)

    def test_a_sent_wave_does_not_fire_twice(self):
        now = at_central(2026, 9, 7, 21)
        done = {d.marker for d in replay(ROSTER, hours=[20])[20]}
        first = S.due(now, ROSTER, done=done)
        self.assertEqual(len(first), 1)
        again = S.due(now + dt.timedelta(minutes=5), ROSTER,
                      done=done | {first[0].marker})
        self.assertEqual(again, [], "a second tick re-sent the same reply")

    def test_marker_uses_the_icds_own_date_not_utc(self):
        """At 9 PM Eastern it is already tomorrow in UTC."""
        now = at_central(2026, 9, 7, 20)
        d = S.due(now, ROSTER)[0]
        self.assertTrue(d.marker.endswith("2026-09-07"), d.marker)
        self.assertGreater(now.astimezone(dt.timezone.utc).day, 0)

    def test_late_tick_inside_grace_still_fires(self):
        late = at_central(2026, 9, 7, 21) + dt.timedelta(minutes=S.GRACE_MIN)
        got = S.due(late, ROSTER)
        self.assertEqual([d.label for d in got], ["Central"])

    def test_tick_past_grace_does_not_fire(self):
        late = at_central(2026, 9, 7, 21) + dt.timedelta(minutes=S.GRACE_MIN + 5)
        self.assertEqual(S.due(late, ROSTER), [])

    def test_still_owed_an_hour_later_is_the_whole_point_of_the_grace(self):
        """Lucy 3 was busy with the 9 PM intraday boards; the wave must still
        go out when the machine frees up, not be skipped for the night."""
        now = at_central(2026, 9, 7, 21) + dt.timedelta(minutes=40)
        got = S.due(now, ROSTER)          # nothing marked done: nothing sent
        self.assertEqual([d.label for d in got], ["Central"])


class MountainSplitsInSummer(unittest.TestCase):
    """Phoenix does not observe DST. Firing on the label would be an hour off
    for one of them for most of the year."""

    ROSTER = {"demo": ["Den Ver", "Phoe Nix"]}
    ZONES = {"den ver": "America/Denver", "phoe nix": "America/Phoenix"}

    def setUp(self):
        p = mock.patch.dict(Z._BY_NORM, self.ZONES, clear=False)
        p.start()
        self.addCleanup(p.stop)

    def test_september_denver_and_phoenix_fire_an_hour_apart(self):
        night = replay(self.ROSTER)
        at_10, at_11 = night[22], night[23]
        self.assertEqual([list(d.icds) for d in at_10], [["Den Ver"]])
        self.assertEqual([list(d.icds) for d in at_11], [["Phoe Nix"]])

    def test_january_they_share_one_email(self):
        got = S.due(at_central(2027, 1, 4, 22), self.ROSTER)
        self.assertEqual(len(got), 1, "winter Mountain should be ONE wave")
        self.assertEqual(sorted(got[0].icds), ["Den Ver", "Phoe Nix"])
        self.assertEqual(got[0].label, "Mountain")


class UnknownZones(unittest.TestCase):
    def test_an_unharvested_icd_is_never_scheduled(self):
        roster = {"demo": ["Nobody Harvested Me"]}
        for hh in range(17, 24):
            self.assertEqual(S.due(at_central(2026, 9, 7, hh), roster), [],
                             f"scheduled an unknown-zone ICD at {hh}:00")

    def test_unconfirmed_lists_it_so_the_caller_can_say_so(self):
        self.assertEqual(Z.unconfirmed(["Rashad Reed", "Nobody Harvested Me"]),
                         ["Nobody Harvested Me"])


class Weekends(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(Z._BY_NORM, FAKE_ZONES, clear=False)
        p.start()
        self.addCleanup(p.stop)

    def test_saturday_still_sends(self):
        got = replay(ROSTER, day=(2026, 9, 5))[21]
        self.assertEqual([d.label for d in got], ["Central"])

    def test_sunday_night_sends_nothing(self):
        self.assertEqual(S.due(at_central(2026, 9, 6, 21), ROSTER), [])


class SeededTable(unittest.TestCase):
    """What the committed table actually says today — the fact that shapes the
    rollout, so it is asserted rather than remembered."""

    def test_no_seeded_icd_is_pacific(self):
        pac = [i for i, z in Z.ICD_TIMEZONES.items()
               if z == "America/Los_Angeles"]
        self.assertEqual(pac, [], "a Pacific office appeared — the 11 PM wave "
                                  "is now real; re-check the rollout note")

    def test_the_seeded_eastern_offices_are_the_four_measured_ones(self):
        east = sorted(i for i in Z.ICD_TIMEZONES
                      if Z.ZONE_LABEL[Z.ICD_TIMEZONES[i]] == "Eastern")
        self.assertEqual(east, ["Aya Mohamed", "Hammad Ahmed",
                                "Nii Armah", "Salik Ahmed"])


if __name__ == "__main__":
    unittest.main()
