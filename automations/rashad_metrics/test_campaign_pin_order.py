"""The campaign pin must come AFTER the grid has been loaded once.

Measured on Lucy 1 (2026-09-01), impersonating Calvin with campaign 40:

  impersonate -> pin -> p=89          -> the UNPINNED B2B grid, no VL column
  impersonate -> p=89 -> pin -> p=89  -> VL / Presentation, i.e. Energy Wells

Same call, same id; only the order differs. Because the pin ran straight after
impersonation it never took, and the office's column set — and therefore its
board SHAPE — came from whatever had loaded the grid before it. Calvin rendered
`energywell` in the afternoon and `wireless` once the session was re-minted, and
the wireless renderer accepts neither extra_totals nor rate_columns, so Chan's
comparison line and the average columns silently vanished from his board.

The order is the fix, so the order is what this pins. Offline: every collaborator
is stubbed and the call sequence is the assertion.
"""
import datetime as dt
import unittest

from automations.rashad_metrics import knocks_pull as KP


class _StubPage:
    def set_default_timeout(self, _ms):
        pass

    def set_default_navigation_timeout(self, _ms):
        pass


class CampaignPinOrder(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._saved = {}
        # Impersonation succeeds; everything else records that it ran.
        self._patch("_exit_impersonation", lambda page: False)
        self._patch("_navigate_to_office_access", lambda page: True)
        self._patch("_find_owner_and_impersonate",
                    lambda page, name, aliases: ("RQST123", "ok"))
        self._patch("page_rqst", lambda page: "RQST123")
        self._patch("_pin_campaign",
                    lambda page, rqst, camp, verbose=True:
                        self.calls.append(("pin", camp)))
        self._patch("_scrape_day_on_page",
                    lambda page, rqst, target, verbose=True:
                        self.calls.append(("scrape", target)) or [])
        self._saved["nav"] = KP.knocks._navigate
        KP.knocks._navigate = (lambda page, rqst, mdy, **kw:
                               self.calls.append(("grid", mdy)))

    def tearDown(self):
        for name, fn in self._saved.items():
            if name == "nav":
                KP.knocks._navigate = fn
            else:
                setattr(KP, name, fn)

    def _patch(self, name, fn):
        self._saved[name] = getattr(KP, name)
        setattr(KP, name, fn)

    def _run(self, days):
        KP.pull_office_days_on_page(_StubPage(), "Calvin Ribera", {}, days,
                                    verbose=False, campaign="40")

    def test_the_grid_is_loaded_before_the_pin(self):
        self._run([dt.date(2026, 9, 1)])
        kinds = [c[0] for c in self.calls]
        self.assertIn("grid", kinds, "no grid warm-up — the pin will be a no-op")
        self.assertLess(kinds.index("grid"), kinds.index("pin"),
                        "the pin must come AFTER the grid has loaded once")

    def test_the_pin_still_comes_before_any_scrape(self):
        self._run([dt.date(2026, 9, 1)])
        kinds = [c[0] for c in self.calls]
        self.assertLess(kinds.index("pin"), kinds.index("scrape"))

    def test_the_warm_up_happens_once_not_once_per_day(self):
        """A week must not pay seven extra navigations."""
        days = [dt.date(2026, 8, 31), dt.date(2026, 9, 1), dt.date(2026, 9, 2)]
        self._run(days)
        self.assertEqual([c[0] for c in self.calls].count("grid"), 1)
        self.assertEqual([c[0] for c in self.calls].count("scrape"), len(days))

    def test_a_failed_warm_up_does_not_kill_the_pull(self):
        """The warm-up serves the pin; it is not the work."""
        def _boom(page, rqst, mdy, **kw):
            raise RuntimeError("grid stalled")
        KP.knocks._navigate = _boom
        self._run([dt.date(2026, 9, 1)])
        kinds = [c[0] for c in self.calls]
        self.assertIn("pin", kinds)
        self.assertIn("scrape", kinds)


if __name__ == "__main__":
    unittest.main()
