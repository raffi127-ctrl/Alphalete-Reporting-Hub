"""Not asking OwnerVille the same question every hour.

Measured on Lucy 3, 2026-11-19: `ownerville` took 10m19s of a 19m19s run,
because 21 of this week's 29 people are not in OwnerVille at all and each
search costs ~27 seconds. The budget then ran out with 10 names never asked
about -- so the wasted time was also crowding out the searches that might
have found somebody.

    python -m unittest automations.icd_onboarding.test_ov_misses
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path


# The body lives in `eco_steps` since 2026-11-24 so it can run on the
# office's own computer; `R.from_ownerville` is a delegate. Read the
# real body, or this passes on a two-line delegation.
def _ES():
    from automations.icd_onboarding import eco_steps
    return eco_steps


from automations.icd_onboarding import ov_misses as M

WEEK = dt.date(2026, 11, 15)
PEOPLE = ["Jade Starkes", "Angel Cruz", "Penina Heather-Leao"]


class RememberingWhoIsNotThere(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._path = M.PATH
        M.PATH = Path(self.dir.name) / "ov_misses.json"
        self.addCleanup(lambda: setattr(M, "PATH", self._path))

    def test_a_name_nobody_has_asked_about_is_always_searched(self):
        self.assertEqual(M.fresh("raf", WEEK, PEOPLE), PEOPLE)

    def test_a_name_just_missed_is_not_asked_again(self):
        M.remember("raf", WEEK, PEOPLE)
        self.assertEqual(M.fresh("raf", WEEK, PEOPLE), [])

    def test_it_is_asked_again_once_the_miss_goes_stale(self):
        # The point of the cooldown: somebody added at 2pm still gets picked
        # up the same day.
        M.remember("raf", WEEK, PEOPLE)
        later = dt.datetime.now() + dt.timedelta(minutes=M.COOLDOWN_MIN + 1)
        self.assertEqual(M.fresh("raf", WEEK, PEOPLE, now=later), PEOPLE)

    def test_the_cooldown_is_longer_than_the_gap_between_runs(self):
        # Hourly today, every 15 minutes next. A cooldown shorter than the
        # tick saves nothing at all.
        self.assertGreaterEqual(M.COOLDOWN_MIN, 60)

    def test_somebody_who_turns_up_stops_being_treated_as_absent(self):
        M.remember("raf", WEEK, PEOPLE)
        M.forget("raf", WEEK, ["Angel Cruz"])
        self.assertEqual(M.fresh("raf", WEEK, PEOPLE), ["Angel Cruz"])

    def test_one_office_does_not_answer_for_another(self):
        M.remember("raf", WEEK, PEOPLE)
        self.assertEqual(M.fresh("cyrus", WEEK, PEOPLE), PEOPLE)

    def test_a_new_week_is_a_new_question(self):
        M.remember("raf", WEEK, PEOPLE)
        nextweek = WEEK + dt.timedelta(days=7)
        self.assertEqual(M.fresh("raf", nextweek, PEOPLE), PEOPLE)

    def test_the_same_person_spelled_differently_is_the_same_person(self):
        M.remember("raf", WEEK, ["Angel Cruz"])
        self.assertEqual(M.fresh("raf", WEEK, ["  ANGEL   cruz "]), [])

    def test_an_unreadable_cache_asks_rather_than_skips(self):
        M.PATH.parent.mkdir(parents=True, exist_ok=True)
        M.PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(M.fresh("raf", WEEK, PEOPLE), PEOPLE)

    def test_an_unreadable_timestamp_asks_rather_than_skips(self):
        M.PATH.parent.mkdir(parents=True, exist_ok=True)
        M.PATH.write_text(json.dumps(
            {M._key("raf", WEEK, "Angel Cruz"): "whenever"}), encoding="utf-8")
        self.assertEqual(M.fresh("raf", WEEK, ["Angel Cruz"]), ["Angel Cruz"])

    def test_a_cache_it_cannot_write_never_fails_the_run(self):
        M.PATH = Path("/no/such/place/ov_misses.json")
        self.assertEqual(M.remember("raf", WEEK, PEOPLE), len(PEOPLE))


class WhatTheRunDoesWithIt(unittest.TestCase):

    def test_only_names_actually_searched_are_remembered(self):
        # A name the budget never reached has NOT been answered. Recording it
        # would stop it being asked next run either -- the same starvation,
        # made permanent.
        import inspect
        from automations.icd_onboarding import run as R
        src = inspect.getsource(_ES().from_ownerville)
        self.assertIn("asked = ask[:got]", src)

    def test_a_remembered_miss_never_ticks_anything(self):
        import inspect
        from automations.icd_onboarding import run as R
        src = inspect.getsource(_ES().from_ownerville)
        self.assertIn("not ticked", src)


if __name__ == "__main__":
    unittest.main()
