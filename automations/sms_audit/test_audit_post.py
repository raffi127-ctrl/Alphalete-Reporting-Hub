"""The daily/weekly booking-call audit post.

What these pin down is mostly about NOT blaming the wrong person: the
Ringover line is not the caller, a mis-heard name is not a caller, and a
thread with twenty replies is a long post in disguise.
"""
from __future__ import annotations

import unittest

from automations.sms_audit import audit_post as AP


def rec(said="", line="Rafael Hidalgo", office="11280", shown=None, **flags):
    items = {k: {"happened": False, "quote": "", "at": ""}
             for k, _q, _kind in __import__(
                 "automations.sms_audit.call_grade",
                 fromlist=["ITEMS"]).ITEMS}
    for k, quote in flags.items():
        items[k] = {"happened": True, "quote": quote, "at": "0:31"}
    return {"said_their_name": said, "line": line, "office": office,
            "shown": shown, "uuid": "u", "items": items}


class WhoMadeTheCall(unittest.TestCase):

    def test_the_spoken_name_beats_the_line(self):
        """Raf's line alone is used by Danny, Mariana and Dulce."""
        rows = [rec(said="Danny") for _ in range(5)]
        self.assertEqual(AP._who(rows[0], AP._roster(rows)), "Danny")

    def test_a_known_variant_folds_to_the_person(self):
        """George is on Jorge Pena's line 100% of 164 calls."""
        for spoken in ("George", "Letty", "Lettie", "Luddy"):
            rows = [rec(said=spoken) for _ in range(5)]
            got = AP._who(rows[0], AP._roster(rows))
            self.assertIn(got, ("Jorge Pena", "Letty Robinson"), spoken)

    def test_a_different_name_on_someone_elses_line_is_left_alone(self):
        """Taylor is on Zalika's line but is not assumed to BE Zalika —
        a second person sharing a line is likelier than a nickname."""
        rows = [rec(said="Taylor", line="Zalika Henderson") for _ in range(5)]
        self.assertEqual(AP._who(rows[0], AP._roster(rows)), "Taylor")

    def test_an_english_word_is_not_a_caller(self):
        """The intro regex catches "this is who" / "this is for"."""
        rows = [rec(said="who") for _ in range(9)]
        self.assertEqual(AP._who(rows[0], AP._roster(rows)), "Rafael Hidalgo")

    def test_a_one_off_name_falls_back_to_the_line(self):
        """One call is a mis-hearing, not a person with a scorecard."""
        rows = [rec(said="Jakia")] + [rec(said="Danny") for _ in range(5)]
        self.assertEqual(AP._who(rows[0], AP._roster(rows)), "Rafael Hidalgo")


class OnlyFactualFlags(unittest.TestCase):

    def test_a_wrong_location_is_flagged(self):
        rows = [rec(said="Danny", wrong_place="we are located in Irving")
                for _ in range(3)]
        self.assertIn("Danny", AP.offenders(rows))

    def test_a_merely_off_script_call_is_not(self):
        """Four tests found the rubric does not predict show-up, so a
        missed must-do is not something to wake somebody up about."""
        rows = [rec(said="Danny") for _ in range(3)]
        self.assertEqual(AP.offenders(rows), {})


class TheThreadStaysShort(unittest.TestCase):

    def test_only_the_worst_few_get_their_own_reply(self):
        rows = []
        for i in range(12):
            rows += [rec(said="Caller{}".format(i),
                         wrong_place="Irving") for _ in range(3)]
        replies = AP.compose(rows)
        # one summary + MAX_PEOPLE + one "also flagged" line
        self.assertEqual(len(replies), 1 + AP.MAX_PEOPLE + 1)
        self.assertIn("Also flagged", replies[-1])

    def test_nobody_is_dropped_silently(self):
        rows = []
        for i in range(12):
            rows += [rec(said="Caller{}".format(i),
                         wrong_place="Irving") for _ in range(3)]
        tail = AP.compose(rows)[-1]
        for i in range(12):
            self.assertIn("Caller{}".format(i), "\n".join(AP.compose(rows)))

    def test_a_day_with_nothing_audited_posts_nothing(self):
        """[[feedback_never_post_blank]]"""
        title, why = AP.build("99999")
        self.assertIsNone(title)
        self.assertIn("no graded calls", why)


if __name__ == "__main__":
    unittest.main()


class RepeatOffenders(unittest.TestCase):
    """Megan 2026-10-20: "red flag emojis for how many days in a row they
    have been flagged M-F so up to 5 flags and reset"."""

    MON = __import__("datetime").date(2026, 9, 21)

    def _fake(self, by_day):
        """Patch load() so streaks() reads a made-up week."""
        import datetime as dt
        orig = AP.load

        def fake(office, day=None):
            if day is None:
                return [r for rs in by_day.values() for r in rs]
            return by_day.get(day, [])
        AP.load = fake
        self.addCleanup(lambda: setattr(AP, "load", orig))

    def _day(self, n):
        import datetime as dt
        return self.MON + dt.timedelta(days=n)

    def test_consecutive_days_count_up(self):
        flagged = [rec(said="Danny", wrong_place="Irving") for _ in range(3)]
        self._fake({self._day(i): flagged for i in range(4)})
        self.assertEqual(AP.streaks("11280", self._day(3))["Danny"], 4)

    def test_a_clean_day_breaks_the_run(self):
        """Flagged Mon, Tue, clean Wed, flagged Thu is a streak of ONE —
        the point is who is still doing it after being told."""
        flagged = [rec(said="Danny", wrong_place="Irving") for _ in range(3)]
        clean = [rec(said="Danny") for _ in range(3)]
        self._fake({self._day(0): flagged, self._day(1): flagged,
                    self._day(2): clean, self._day(3): flagged})
        self.assertEqual(AP.streaks("11280", self._day(3))["Danny"], 1)

    def test_it_stops_at_five(self):
        flagged = [rec(said="Danny", wrong_place="Irving") for _ in range(3)]
        self._fake({self._day(i): flagged for i in range(5)})
        self.assertEqual(AP.streaks("11280", self._day(4))["Danny"], 5)

    def test_the_week_is_monday_to_friday_only(self):
        """Monday starts again — last week's run does not carry over."""
        self.assertEqual(len(AP.week_days(self.MON)), 1)
        self.assertEqual(len(AP.week_days(self._day(4))), 5)

    def test_a_longer_streak_outranks_more_flags_today(self):
        # both need >= MIN_CALLS so neither falls back to the line name
        rows = ([rec(said="Streaky", wrong_place="Irving")
                 for _ in range(3)]
                + [rec(said="Noisy", wrong_place="Irving") for _ in range(9)])
        replies = AP.compose(rows, {"Streaky": 4, "Noisy": 1})
        self.assertIn("Streaky", replies[1])
        self.assertIn("\U0001F6A9" * 4, replies[1])
        self.assertIn("Noisy", replies[2])
