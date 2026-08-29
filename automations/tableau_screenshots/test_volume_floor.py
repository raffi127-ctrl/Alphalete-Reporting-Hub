"""The volume floor: a settled number still has to be a BELIEVABLE day.

Built from the 2026-08-29 failure, so the numbers here are the real ones. That
morning NDS Friday read 280 against a Mon-Thu of ~1,050 and sat there from 04:01
to 08:52; the stability gate called it "unchanged for 289m — finished loading"
on all three runners and sixteen channels got a -70% Friday that never happened.
"""
import datetime as dt
import unittest

from automations.tableau_screenshots import freshness as fr

FRI = dt.date(2026, 8, 28)          # the day that was part-loaded
MON = dt.date(2026, 8, 24)
TUE = dt.date(2026, 8, 25)
SAT = dt.date(2026, 8, 29)

# Layout 1 (att / b2b) — "Summary Product by Day", the day is a COLUMN.
COLS = "\n".join([
    "Summary Product by Day: 08-24 - 08-28",
    "Product Type\tMon (08-24)\tTue (08-25)\tWed (08-26)\tThu (08-27)\t"
    "Fri (08-28)\tTotal",
    "Grand Total\t1,310\t1,413\t1,350\t1,290\t461\t5,824",
])

# Layout 2 (nds) — "New/Port/Air", the day is a ROW keyed by weekday name.
ROWS = "\n".join([
    "New/Port/Air: 08/24 - 08/28",
    "\tLine New/Port/Air\tvs Prev Wk",
    "Monday\t08/23 - 08/24\t1,038\t14%",
    "Tuesday\t08/24 - 08/25\t1,075\t5%",
    "Wednesday\t08/25 - 08/26\t1,050\t4%",
    "Thursday\t08/26 - 08/27\t1,053\t14%",
    "Friday\t08/27 - 08/28\t280\t-70%",
    "Total\t\t4,469\t-7%",
])


class TestBaseline(unittest.TestCase):
    """The week's other business days, read off the same crosstab."""

    def test_columns_layout(self):
        """Mon is MISSING here, and that is a pre-existing parse_day_total quirk,
        not the floor's doing: the sheet TITLE ("... : 08-24 - 08-28") carries the
        week's start date, so a Monday lookup matches the title row first, reads
        the non-numeric cell under it, and gives up before the real column. The
        floor degrades gracefully — three days is still a baseline — so this is
        pinned rather than worked around. It does mean the main gate silently
        fails open on a MONDAY target for this layout; see the spawned task."""
        base = fr.week_baseline_totals(COLS, FRI)
        self.assertEqual({d.day: v for d, v in base.items()},
                         {25: 1413.0, 26: 1350.0, 27: 1290.0})
        # Still comfortably enough to catch the real 461.
        self.assertIsNotNone(fr.volume_shortfall(COLS, FRI, 461.0))

    def test_rows_layout(self):
        base = fr.week_baseline_totals(ROWS, FRI)
        self.assertEqual({d.day: v for d, v in base.items()},
                         {24: 1038.0, 25: 1075.0, 26: 1050.0, 27: 1053.0})

    def test_monday_has_no_baseline(self):
        self.assertEqual(fr.week_baseline_totals(COLS, MON), {})


class TestVolumeShortfall(unittest.TestCase):

    def test_holds_the_real_nds_friday(self):
        why = fr.volume_shortfall(ROWS, FRI, 280.0)
        self.assertIsNotNone(why)
        # stale_boards only HOLDS a board when the reason says this.
        self.assertIn("extract not refreshed", why)
        self.assertIn("280", why)

    def test_holds_the_real_att_friday(self):
        self.assertIsNotNone(fr.volume_shortfall(COLS, FRI, 461.0))

    def test_allows_a_normal_friday(self):
        """A real Friday runs level with midweek — it must sail through."""
        self.assertIsNone(fr.volume_shortfall(ROWS, FRI, 1012.0))

    def test_allows_a_merely_soft_friday(self):
        """Only a landslide may hold: 60% of midweek is a bad day, not a broken
        feed, and holding it would cost the morning's boards for nothing."""
        self.assertIsNone(fr.volume_shortfall(ROWS, FRI, 640.0))

    def test_fires_just_below_the_line(self):
        median = 1051.5                      # (1050 + 1053) / 2
        self.assertIsNone(fr.volume_shortfall(ROWS, FRI, median * 0.5))
        self.assertIsNotNone(fr.volume_shortfall(ROWS, FRI, median * 0.5 - 1))

    def test_thin_baseline_never_fires(self):
        """Tuesday has one prior day. One number is an anecdote."""
        self.assertIsNone(fr.volume_shortfall(COLS, TUE, 1.0))

    def test_weekend_never_fires(self):
        """Saturday is legitimately near-zero, not broken."""
        self.assertIsNone(fr.volume_shortfall(COLS, SAT, 0.0))

    def test_unreadable_week_never_fires(self):
        """An unreadable week is not evidence of a bad one — fail open."""
        self.assertIsNone(fr.volume_shortfall("", FRI, 1.0))
        self.assertIsNone(fr.volume_shortfall("garbage\tnonsense", FRI, 1.0))


class TestWiredIntoTheGate(unittest.TestCase):
    """The floor has to actually reach _check_stable_total's verdict."""

    def setUp(self):
        self.calls = []
        fr._record_observation = lambda *a, **k: [("t1", 280.0), ("t2", 280.0)]

    def test_stable_but_part_loaded_is_held(self):
        cfg = {"stable_total": {"view_url": "u", "sheet": "New/Port/Air"}}
        import automations.shared.tableau_patchright as tp
        tp.download_crosstab_patchright = lambda *a, **k: "/tmp/x.csv"
        fr._read_crosstab_text = lambda p: ROWS

        ok, why = fr._check_stable_total("tableau:tracker_nds", cfg, FRI,
                                         dt.date(2026, 8, 29))
        self.assertFalse(ok, "a part-loaded day must be HELD, not posted")
        self.assertIn("extract not refreshed", why)

    def test_full_day_still_passes(self):
        cfg = {"stable_total": {"view_url": "u", "sheet": "New/Port/Air"}}
        import automations.shared.tableau_patchright as tp
        tp.download_crosstab_patchright = lambda *a, **k: "/tmp/x.csv"
        good = ROWS.replace("Friday\t08/27 - 08/28\t280\t-70%",
                            "Friday\t08/27 - 08/28\t1,012\t-3%")
        fr._read_crosstab_text = lambda p: good
        fr._record_observation = lambda *a, **k: [
            ("2026-08-29T04:01:00", 1012.0), ("2026-08-29T04:31:00", 1012.0)]

        ok, why = fr._check_stable_total("tableau:tracker_nds", cfg, FRI,
                                         dt.date(2026, 8, 29))
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
