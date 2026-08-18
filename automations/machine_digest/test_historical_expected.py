"""What the 'didn't run today' baseline expects to see today.

Regression cover for 2026-08-18: Applicant Push (daily, live since 8/4) died on
Mon 8/17 and NOTHING alerted for the whole day — the same-weekday baseline needs
two prior same-weekdays and Monday only had one (8/10). The alert only landed
Tuesday, once Tuesday had two. The daily-cadence path closes that hole; these
tests pin both it and the weekend false-positives it must NOT create.
"""
import datetime as dt
import unittest

from automations.machine_digest.run import _historical_expected


def _rows(card, days, hour=7, name=None, machine="Lucys-MacBook-Neo.local"):
    return [{"Started At": f"{d.isoformat()}T{hour:02d}:05:00", "Report ID": card,
             "Report Name": name or card, "Machine": machine} for d in days]


def _span(target, start, end):
    """Dates from `start` to `end` days before `target`, inclusive."""
    return [target - dt.timedelta(days=n) for n in range(start, end + 1)]


class HistoricalExpected(unittest.TestCase):
    def test_young_daily_report_is_expected_on_a_weekday_it_hit_only_once(self):
        """THE 8/17 MISS. Daily since 8/4; on Mon 8/17 the 3-week weekday window
        holds a single Monday (8/10), so the weekday path stays silent — the
        daily path must cover it."""
        target = dt.date(2026, 8, 17)
        rows = _rows("applicant-push", _span(target, 1, 13), name="Applicant Push")
        exp = _historical_expected(rows, target)
        self.assertIn("applicant-push", exp)
        self.assertEqual(exp["applicant-push"]["start_hour"], 7)
        self.assertEqual(exp["applicant-push"]["name"], "Applicant Push")
        # and the weekday path alone genuinely does NOT catch it (the bug)
        self.assertNotIn("applicant-push",
                         _historical_expected(rows, target, daily_min_days=99))

    def test_weekday_only_report_is_not_expected_on_the_weekend(self):
        """A Mon-Fri report also clears 5-of-7 density, so density alone would
        post 'didn't run today' every Saturday. The same-weekday proof stops it."""
        target = dt.date(2026, 8, 15)          # Saturday
        weekdays = [d for d in _span(target, 1, 21) if d.weekday() < 5]
        self.assertNotIn("daily-focus",
                         _historical_expected(_rows("daily-focus", weekdays), target))

    def test_weekday_only_report_is_still_expected_on_a_weekday(self):
        target = dt.date(2026, 8, 13)          # Thursday
        weekdays = [d for d in _span(target, 1, 21) if d.weekday() < 5]
        self.assertIn("daily-focus",
                      _historical_expected(_rows("daily-focus", weekdays), target))

    def test_still_expected_on_day_two_of_an_outage(self):
        """The watcher must not go quiet on the second dead day — that would hide
        exactly the failure it exists to report."""
        target = dt.date(2026, 8, 18)
        ran = _span(target, 2, 14)             # everything except yesterday
        self.assertIn("applicant-push", _historical_expected(_rows("applicant-push", ran), target))

    def test_retired_daily_report_drops_out(self):
        """Dead for a week+ → no same-weekday hit → it stops being expected,
        instead of alerting forever."""
        target = dt.date(2026, 8, 18)
        ran = _span(target, 8, 21)
        self.assertNotIn("applicant-push", _historical_expected(_rows("applicant-push", ran), target))

    def test_occasional_report_is_never_expected(self):
        target = dt.date(2026, 8, 18)
        ran = [target - dt.timedelta(days=n) for n in (1, 4)]
        self.assertNotIn("one-off", _historical_expected(_rows("one-off", ran), target))

    def test_start_hour_anchors_to_the_most_recent_day(self):
        """A one-off early test run days ago must not drag the alert time earlier."""
        target = dt.date(2026, 8, 18)
        rows = _rows("applicant-push", _span(target, 1, 6), hour=7)
        rows += _rows("applicant-push", [target - dt.timedelta(days=7)], hour=3)
        self.assertEqual(_historical_expected(rows, target)["applicant-push"]["start_hour"], 7)


if __name__ == "__main__":
    unittest.main()
