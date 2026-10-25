"""The org board's BOX pull says when Tableau is behind (2026-10-25).

The Org email for 10/24 was HELD for "BOX: Saturday 10/24 column blank for
every owner" — SCI's Box extract had stopped at Thu 10/22, and nothing told
the email gate, because the BOX crosstab has its days as column headers and no
date column for shared/tableau_freshness to judge. section_pull.note_lag now
writes the state the gate reads (board_emails.auto_send.stale_sources).

Offline: STATE_DIR is a temp dir, and the two calls that could reach Slack
(section_drop_alert.alert, incident_thread via clear_stale) are patched on the
real modules — never through sys.modules.

    python -m unittest automations.org_sales_board.test_box_lag
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.org_sales_board import section_pull as sp
from automations.shared import section_drop_alert as sda
from automations.shared import tableau_freshness as tf

SUN = dt.date(2026, 10, 25)
TUE = dt.date(2026, 10, 27)
LABEL = "B2BBOXEnergyTracker/BoxDailyTracker → Daily Tracker Sales"


def pull_through(last: dt.date):
    """Two owners with a value every day Mon 10/19 .. `last`."""
    days = []
    d = dt.date(2026, 10, 19)
    while d <= last:
        days.append(d)
        d += dt.timedelta(days=1)
    return {o: {"count": {d: 3 for d in days}} for o in ("roshan ahmad",
                                                         "joy gray")}


class BoxLagTest(unittest.TestCase):
    def setUp(self):
        self.sd = Path(tempfile.mkdtemp())
        for target, attr, kw in ((tf, "STATE_DIR", {"new": self.sd}),
                                 (sda, "alert", {}),
                                 (tf, "clear_stale", {})):
            p = mock.patch.object(target, attr, **kw)
            m = p.start()
            self.addCleanup(p.stop)
            if attr == "alert":
                self.sda_alert = m
            if attr == "clear_stale":
                self.clear = m
        self.log = []

    def state(self, day=SUN):
        p = self.sd / "{}-{}.json".format(tf._slug(LABEL + " [org board days]"),
                                          day.isoformat())
        return json.loads(p.read_text("utf-8")) if p.exists() else {}

    def lag(self, parsed, today=SUN):
        return sp.note_lag(sp.BOX_SPEC, parsed, today, logfn=self.log.append)

    def test_bar_is_day_behind_and_skips_sundays(self):
        self.assertEqual(sp.lag_needs(sp.BOX_SPEC, SUN), dt.date(2026, 10, 23))
        # Monday reports the closed week: Sunday is never owed, Friday is.
        self.assertEqual(sp.lag_needs(sp.BOX_SPEC, dt.date(2026, 10, 26)),
                         dt.date(2026, 10, 23))
        # Tuesday the week rolled: the pinned week can't show the bar day.
        self.assertIsNone(sp.lag_needs(sp.BOX_SPEC, TUE))
        # Not a day-behind source: not judged here at all.
        self.assertIsNone(sp.lag_needs(sp.FIBER_SPEC, SUN))

    def test_box_stuck_at_thursday_records_late_state(self):
        r = self.lag(pull_through(dt.date(2026, 10, 22)))
        self.assertTrue(r["late"])
        st = self.state()
        self.assertTrue(st["alerted"])
        self.assertEqual(st["reports"], ["org_sales_board"])
        self.assertEqual(st["newest"], "2026-10-22")
        self.assertEqual(st["section"], "BOX")
        self.assertEqual(self.sda_alert.call_count, 1)   # one line, first time
        self.lag(pull_through(dt.date(2026, 10, 22)))    # catch-up run
        self.assertEqual(self.sda_alert.call_count, 1)   # deduped

    def test_no_new_alert_when_the_workbook_already_has_one(self):
        # Order Log / the frozen bar already opened Box's workbook thread today.
        tf._save_state("B2BBOXEnergyTracker workbook", SUN,
                       {"alerted": True, "reports": ["box_order_log"],
                        "view": "B2BBOXEnergyTracker"})
        self.lag(pull_through(dt.date(2026, 10, 22)))
        self.assertFalse(self.sda_alert.called)
        self.assertTrue(self.state()["alerted"])          # gate still sees it

    def test_on_time_box_records_nothing(self):
        r = self.lag(pull_through(dt.date(2026, 10, 23)))
        self.assertFalse(r["late"])
        self.assertEqual(self.state(), {})
        self.assertFalse(self.sda_alert.called)

    def test_catching_up_releases_the_email(self):
        self.lag(pull_through(dt.date(2026, 10, 22)))
        wb = tf._load_state("B2BBOXEnergyTracker workbook", SUN)
        self.assertIn("org_sales_board", wb.get("reports") or [])
        self.lag(pull_through(dt.date(2026, 10, 24)))
        st = self.state()
        self.assertFalse(st["alerted"])
        self.assertEqual(st["caught_up"], "2026-10-24")
        wb = tf._load_state("B2BBOXEnergyTracker workbook", SUN)
        self.assertNotIn("org_sales_board", wb.get("reports") or [])
        self.assertTrue(self.clear.called)

    def test_tuesday_empty_week_is_not_judged(self):
        self.assertIsNone(self.lag({}, today=TUE))
        self.assertEqual(self.state(TUE), {})

    def test_newest_day(self):
        self.assertEqual(sp.newest_day(pull_through(dt.date(2026, 10, 22)),
                                       "count"), dt.date(2026, 10, 22))
        self.assertIsNone(sp.newest_day({}, "count"))


if __name__ == "__main__":
    unittest.main()
