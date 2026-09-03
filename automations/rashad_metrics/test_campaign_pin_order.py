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
        # The identity guard is REAL work in the sequence, not scenery — since
        # 2026-09-02 it raises rather than shrugging when it can't read the
        # office, so a stub page that answers nothing would fail this test for
        # a reason that has nothing to do with pin order. Recorded, so the
        # order test also pins that the guard runs before anything is scraped.
        self._patch("assert_impersonating",
                    lambda page, rqst, canonical, aliases, verbose=True:
                        self.calls.append(("assert", canonical)))
        self._patch("_pin_campaign",
                    lambda page, rqst, camp, verbose=True:
                        self.calls.append(("pin", camp)))
        # **kw so a new keyword on the real function (expect_campaign, added
        # 2026-09-02 to prove the pin took) doesn't fail this as a TypeError —
        # this test is about ORDER, not signature.
        self._patch("_scrape_day_on_page",
                    lambda page, rqst, target, verbose=True, **kw:
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

    def test_identity_is_proved_before_a_single_number_is_read(self):
        """Khalil Mansour, 2026-09-02: the guard was skipped and /knocks
        published Raf's reps under his name. Nothing may be scraped first."""
        self._run([dt.date(2026, 9, 1)])
        kinds = [c[0] for c in self.calls]
        self.assertIn("assert", kinds)
        self.assertLess(kinds.index("assert"), kinds.index("scrape"))

    def test_every_day_is_re_checked_because_the_session_drifts(self):
        """One ownerville SERVER session is shared by every process on the
        machine, whatever Chrome profile each launched, so another run's
        impersonation — or its exit, which drops the session back to Raf —
        lands mid-pull. Measured on Lucy 1 2026-09-02: four reads of Khalil's
        09/01 inside ONE impersonation went 7, 7, 39, 39 reps, the last two
        being Chan Park's, with nothing raising.

        So the check runs once up front AND after each day's rows, and a day
        is kept only if the session is still on the right office.
        """
        days = [dt.date(2026, 8, 31), dt.date(2026, 9, 1), dt.date(2026, 9, 2)]
        self._run(days)
        kinds = [c[0] for c in self.calls]
        self.assertEqual(kinds.count("assert"), len(days) + 1)
        # ... and each one lands AFTER the scrape whose rows it vouches for.
        for i, kind in enumerate(kinds):
            if kind == "scrape":
                self.assertEqual(kinds[i + 1], "assert",
                                 "a day's rows were kept without re-checking "
                                 "which office answered for them")

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
