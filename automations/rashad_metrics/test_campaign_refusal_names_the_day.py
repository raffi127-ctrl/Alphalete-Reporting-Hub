"""A campaign refusal inside a weekly pull says WHICH DAY refused.

2026-11-16: Carlos Hidalgo's weekly pull (Mon-Sat inside one impersonation)
failed three days running with

    campaign 2 (B2B AT&T SBS) was pinned, but the Disposition grid on screen
    is not a B2B grid at all ...

and nothing anywhere said which of the six days produced that grid. The
capture runs non-verbose, so its log held only "Disposition by Rep 2026-11-09
→ 2026-11-14 (Carlos Hidalgo) — day by day" followed by the failure. Finding
the day took SIX probe_knocks runs against ownerville, one per day, while the
date sat in a local variable in the function that raised.

Same family as knocks_audit truncating "Headers seen:" off its own alert: the
failure was reported and the one fact needed to act on it was not.

Run:  python -m unittest automations.rashad_metrics.test_campaign_refusal_names_the_day
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.rashad_metrics import knocks_pull as KP
from automations.total_knocks.pull import KnocksPullFailed


class _StubPage:
    def set_default_timeout(self, *a, **k):
        pass

    def set_default_navigation_timeout(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass


class TheRefusalNamesTheDay(unittest.TestCase):
    """Driven through _scrape_day_on_page, the function that owns both the date
    and the assertion."""

    def setUp(self):
        self._nav = KP.knocks._navigate
        self._hdr = KP.knocks._header_index
        # A grid with NO B2B signature column: what the refusal is about.
        KP.knocks._navigate = lambda page, rqst, mdy, **k: None
        KP.knocks._header_index = lambda page: {"rep": 0, "total knocks": 1}

    def tearDown(self):
        KP.knocks._navigate = self._nav
        KP.knocks._header_index = self._hdr

    def test_the_date_is_in_the_message(self):
        with self.assertRaises(KnocksPullFailed) as ctx:
            KP._scrape_day_on_page(_StubPage(), "rqst123",
                                   dt.date(2026, 11, 10),
                                   verbose=False, expect_campaign="2")
        self.assertIn("11/10/2026", str(ctx.exception))

    def test_the_original_reason_is_still_there(self):
        with self.assertRaises(KnocksPullFailed) as ctx:
            KP._scrape_day_on_page(_StubPage(), "rqst123",
                                   dt.date(2026, 11, 10),
                                   verbose=False, expect_campaign="2")
        msg = str(ctx.exception)
        self.assertIn("campaign 2", msg)
        self.assertIn("B2B AT&T SBS", msg)
        self.assertIn("Headers seen", msg,
                      "the header list must survive the re-raise")

    def test_each_day_names_itself(self):
        got = []
        for d in (dt.date(2026, 11, 9), dt.date(2026, 11, 14)):
            try:
                KP._scrape_day_on_page(_StubPage(), "r", d, verbose=False,
                                       expect_campaign="2")
            except KnocksPullFailed as e:
                got.append(str(e))
        self.assertIn("11/09/2026", got[0])
        self.assertIn("11/14/2026", got[1])

    def test_an_unguarded_campaign_still_does_not_raise(self):
        # expect_campaign None = nothing to verify; the guard no-ops and the
        # date wrapper must not invent a failure.
        try:
            KP._scrape_day_on_page(_StubPage(), "r", dt.date(2026, 11, 10),
                                   verbose=False, expect_campaign=None)
        except KnocksPullFailed as e:  # pragma: no cover
            self.fail("a no-op guard raised: %s" % e)
        except Exception:
            pass   # anything later in the scrape is not this test's business


if __name__ == "__main__":
    unittest.main()
