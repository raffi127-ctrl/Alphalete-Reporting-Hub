"""What the 'didn't run today' baseline expects to see today.

Regression cover for 2026-08-18: Applicant Push (daily, live since 8/4) died on
Mon 8/17 and NOTHING alerted for the whole day — the same-weekday baseline needs
two prior same-weekdays and Monday only had one (8/10). The alert only landed
Tuesday, once Tuesday had two. The daily-cadence path closes that hole; these
tests pin both it and the weekend false-positives it must NOT create.
"""
import datetime as dt
import unittest

from automations.machine_digest.run import _historical_expected, _offday_standalone_ids


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

    def test_a_daily_report_that_moved_later_is_not_flagged_at_its_old_hour(self):
        """THE 8/20-8/23 NOISE. enrollment_pending_check left the 4am pass for a
        09:00-22:00 hourly agent on 8/19. The weekday path anchors to the same
        weekday SEVEN days back — still 4:00 — so the watcher posted 'didn't run
        today · usually starts ~4:00' four mornings running, each one resolved by
        the 9:00 run that was never late. The daily anchor (most recent day it
        actually ran) has to win."""
        target = dt.date(2026, 8, 23)
        rows = _rows("enrollment_pending_check", _span(target, 5, 21), hour=4)
        rows += _rows("enrollment_pending_check", _span(target, 1, 4), hour=9)
        exp = _historical_expected(rows, target)
        self.assertIn("enrollment_pending_check", exp)
        self.assertEqual(exp["enrollment_pending_check"]["start_hour"], 9)

    def test_the_machine_refreshes_with_the_hour(self):
        """Same staleness, same fix: that agent moved to Lucy 1, and the alert
        kept saying 'on the mini'."""
        target = dt.date(2026, 8, 23)
        rows = _rows("enrollment_pending_check", _span(target, 5, 21), hour=4,
                     machine="Alphaletes-Mac-mini.local")
        rows += _rows("enrollment_pending_check", _span(target, 1, 4), hour=9,
                      machine="Lucys-MacBook-Pro.local")
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["enrollment_pending_check"]["machine"],
                         "Lucys-MacBook-Pro.local")

    def test_a_stable_daily_report_keeps_its_hour(self):
        """The refresh must be a no-op for everything that didn't move."""
        target = dt.date(2026, 8, 23)
        rows = _rows("daily-metrics", _span(target, 1, 21), hour=4)
        self.assertEqual(
            _historical_expected(rows, target)["daily-metrics"]["start_hour"], 4)

    def test_a_weekly_report_is_untouched_by_the_daily_refresh(self):
        """A weekly report never clears the daily density bar, so its hour still
        comes from the same-weekday anchor — unchanged behaviour."""
        target = dt.date(2026, 8, 23)                      # Sunday
        sundays = [target - dt.timedelta(days=7 * w) for w in (1, 2, 3)]
        rows = _rows("weekly-knock-dispositions", sundays, hour=6)
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["weekly-knock-dispositions"]["start_hour"], 6)

    def test_a_late_manual_rerun_does_not_move_the_hour(self):
        """A 4am run plus a 2pm re-run on the same day is still a 4am report —
        hour_by_day keeps the earliest start, so the anchor stays 4."""
        target = dt.date(2026, 8, 23)
        rows = _rows("daily-metrics", _span(target, 1, 21), hour=4)
        rows += _rows("daily-metrics", [target - dt.timedelta(days=1)], hour=14)
        self.assertEqual(
            _historical_expected(rows, target)["daily-metrics"]["start_hour"], 4)


class _Cfg:
    def __init__(self, reports):
        self.raw = {"reports": reports}


class OffdayStandaloneIds(unittest.TestCase):
    """Regression cover for 2026-08-22: dd_gross_revenue runs the 1st & 15th at
    noon (plist Day 1/15), and in August 2026 both fell on Saturdays — so the
    weekday baseline learned 'weekly Saturday report' and posted 'didn't run
    today' on Sat 8/22 while nothing was wrong. `standalone_monthdays` pins the
    real day-of-month schedule the way `standalone_weekdays` pins vantura's
    Wednesday."""

    MONTHLY = _Cfg({"dd_gross_revenue": {"standalone_monthdays": [1, 15]}})

    def test_monthdays_report_is_exempt_on_an_off_day(self):
        # Sat 8/22 — the false-alarm day.
        self.assertIn("dd_gross_revenue",
                      _offday_standalone_ids(self.MONTHLY, dt.date(2026, 8, 22)))

    def test_monthdays_report_is_watched_on_its_run_days(self):
        for d in (dt.date(2026, 8, 15), dt.date(2026, 9, 1), dt.date(2026, 9, 15)):
            self.assertNotIn("dd_gross_revenue",
                             _offday_standalone_ids(self.MONTHLY, d))

    def test_weekday_pin_still_works_alone(self):
        cfg = _Cfg({"vantura_payroll": {"standalone_weekdays": [2]}})   # Wed
        self.assertIn("vantura_payroll", _offday_standalone_ids(cfg, dt.date(2026, 8, 20)))
        self.assertNotIn("vantura_payroll", _offday_standalone_ids(cfg, dt.date(2026, 8, 19)))

    def test_both_pins_declared_means_both_must_match(self):
        # launchd's Day+Weekday AND rule: 9/15/2026 is a Tuesday (weekday 1).
        cfg = _Cfg({"r": {"standalone_weekdays": [1], "standalone_monthdays": [15]}})
        self.assertNotIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 15)))
        self.assertIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 14)))   # Mon the 14th
        self.assertIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 22)))   # Tue the 22nd

    def test_undeclared_report_keeps_the_historical_guess(self):
        cfg = _Cfg({"plain": {}})
        self.assertNotIn("plain", _offday_standalone_ids(cfg, dt.date(2026, 8, 22)))


if __name__ == "__main__":
    unittest.main()
