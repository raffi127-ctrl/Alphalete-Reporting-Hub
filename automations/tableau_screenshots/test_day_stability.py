"""Has yesterday STOPPED loading? — the gate every earlier one failed.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_day_stability

WHAT HAPPENED (2026-08-26). Two gates shipped that morning and both passed every
board, because both asked whether yesterday was PRESENT. It was — partially:

                   4:11am (posted)      10:30am        drift
  NDS Tuesday      744                  1,075          +44%
  AT&T Tuesday     1,118                1,413          +26%
  B2B Tuesday      1,033                1,040          +0.7%

A third of a day and a whole day are indistinguishable to a max-date test, so
NDS and AT&T went to 15 channels understated by a quarter to a half. Megan had
said it plainly at the start — "trackers are all behind" — and the first analysis
here judged each day against its own baselines and concluded only one board was
wrong. That method cannot work when the whole morning's load is partial: the
baselines are what a full day looks like, and every board was short.

So the question stops being "is it there" and becomes "has it stopped moving".
Two samples STABILITY_GAP_MIN apart that agree = done. Megan chose the trade
explicitly: "later and correct is fine."
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.tableau_screenshots import freshness as fr


TUE = dt.date(2026, 8, 25)
WED = dt.date(2026, 8, 26)

# Real exports, tabs and all.
NDS_SHEET = (
    "\t\tLine New/Port/Air\tvs Prev Wk Line New/Port/Air %\n"
    "Monday\t08/24 - 08/25\t1,038\t14%\n"
    "Tuesday\t08/24 - 08/25\t1,075\t5%\n"
    "Wednesday\t08/24 - 08/25\t\t\n"
    "Total\tTotal\t2,107\t9%\n")

ATT_SHEET = (
    "\t\tThis Week\tThis Week\tGrand Total\n"
    "Product Type (Broken Out)\tTest is best day ever?\tMon (08-24)\tTue (08-25)\tTotal\n"
    "AIR\tFalse\t10\t13\t\n"
    "NEW INTERNET\tFalse\t800\t876\t\n"
    "Grand Total\tTotal\t1,310\t1,413\n")


class ParseDayTotalTest(unittest.TestCase):

    def test_column_layout_att_b2b(self):
        self.assertEqual(1413.0, fr.parse_day_total(ATT_SHEET, TUE))

    def test_row_layout_nds(self):
        self.assertEqual(1075.0, fr.parse_day_total(NDS_SHEET, TUE))

    def test_it_reads_the_asked_for_day_not_the_last_one(self):
        self.assertEqual(1310.0, fr.parse_day_total(ATT_SHEET, dt.date(2026, 8, 24)))
        self.assertEqual(1038.0, fr.parse_day_total(NDS_SHEET, dt.date(2026, 8, 24)))

    def test_a_day_the_sheet_does_not_carry_is_none(self):
        self.assertIsNone(fr.parse_day_total(ATT_SHEET, dt.date(2026, 8, 19)))

    def test_percentages_and_date_ranges_are_not_totals(self):
        """'5%' and '08/24 - 08/25' sit between the weekday and its number."""
        self.assertIsNone(fr._num("5%"))
        self.assertIsNone(fr._num("08/24 - 08/25"))
        self.assertEqual(1075.0, fr._num("1,075"))

    def test_an_empty_sheet_is_none_not_zero(self):
        """None means 'could not read' (fail open); 0 would mean 'no sales',
        which is a HOLD. They must never collapse into each other."""
        self.assertIsNone(fr.parse_day_total("", TUE))


class StableTotalVerdictTest(unittest.TestCase):

    EXTRACT = "tableau:tracker_nds"

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self._real_file = fr.STABILITY_FILE
        fr.STABILITY_FILE = tmp / "_stability.json"
        self.addCleanup(setattr, fr, "STABILITY_FILE", self._real_file)
        # Local samples only: these cases are about the VERDICT, and a unit test
        # must never reach the shared Mini Control tab. The cross-machine merge
        # has its own class below.
        fr.SHARED_SAMPLES = False
        self.addCleanup(setattr, fr, "SHARED_SAMPLES", True)
        self._stub(NDS_SHEET)

    def _stub(self, text: str):
        from automations.shared import tableau_patchright as tp
        tmp = Path(tempfile.mkdtemp()) / "day.csv"
        tmp.write_bytes(text.encode("utf-16"))
        real = getattr(tp, "download_crosstab_patchright")
        tp.download_crosstab_patchright = lambda *a, **k: tmp
        self.addCleanup(setattr, tp, "download_crosstab_patchright", real)

    def _seed(self, series):
        fr.STABILITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fr.STABILITY_FILE.write_text(json.dumps(
            {"date": WED.isoformat(), "obs": {self.EXTRACT: series}}))

    def _check(self):
        return fr._check_stable_total(self.EXTRACT, fr.EXTRACTS[self.EXTRACT],
                                      TUE, WED)

    def test_the_first_sample_is_never_enough(self):
        """One reading cannot distinguish 744 from 1,075 — that is the whole bug."""
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("first sample", why)
        self.assertIn("not refreshed", why)

    def test_a_growing_day_is_held(self):
        """744 at 04:11, 1,075 now: still loading."""
        self._seed([["2026-08-26T04:11:00", 744]])
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("grew", why)
        self.assertIn("not refreshed", why)

    def test_two_equal_samples_far_enough_apart_pass(self):
        self._seed([["2026-08-26T04:11:00", 1075]])
        ok, why = self._check()
        self.assertTrue(ok, why)
        self.assertIn("finished loading", why)

    def test_equal_but_too_close_together_is_not_proof(self):
        """A slow trickle can hold the same value for a minute or two."""
        near = (dt.datetime.now() - dt.timedelta(minutes=2)).isoformat(
            timespec="seconds")
        self._seed([[near, 1075]])
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("apart", why)

    def test_a_day_with_no_data_never_counts_as_settled(self):
        """Two matching zeros must not read as 'stable'. quantum on 8/26 showed
        0 sales all morning; twice-zero is exactly how that board would slip
        through a naive stability check."""
        self._stub(NDS_SHEET.replace("Tuesday\t08/24 - 08/25\t1,075",
                                     "Tuesday\t08/24 - 08/25\t0"))
        self._seed([["2026-08-26T04:11:00", 0]])
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("hasn't loaded", why)

    def test_an_unreadable_sheet_fails_open(self):
        self._stub("totally different layout\n")
        ok, why = self._check()
        self.assertTrue(ok)
        self.assertIn("not held", why)

    def test_a_pull_failure_fails_open(self):
        from automations.shared import tableau_patchright as tp

        def boom(*a, **k):
            raise RuntimeError("tableau flaked")
        real = tp.download_crosstab_patchright
        tp.download_crosstab_patchright = boom
        self.addCleanup(setattr, tp, "download_crosstab_patchright", real)
        ok, why = self._check()
        self.assertTrue(ok)
        self.assertIn("not held", why)

    def test_yesterdays_samples_are_not_reused(self):
        """A value that was stable yesterday says nothing about today."""
        fr.STABILITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fr.STABILITY_FILE.write_text(json.dumps(
            {"date": "2026-08-25", "obs": {self.EXTRACT: [["x", 1075]]}}))
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("first sample", why)


class StabilityGapTest(unittest.TestCase):
    """The gap is paid EVERY morning, not just a bad one.

    The trackers run first in the orchestrator's order, so the first sample is
    the run's own and no board can post until a second one lands. At 20 minutes
    a perfectly normal 4:11 thread slipped to ~4:30 daily. Megan chose 10: the
    failure this gate catches was NDS still growing hours later (744 -> 1,075),
    which 10 minutes separates just as cleanly at half the cost."""

    def test_the_gap_is_short_enough_not_to_tax_a_good_morning(self):
        self.assertLessEqual(fr.STABILITY_GAP_MIN, 15,
                             "a longer gap delays every normal day's boards")

    def test_the_gap_is_long_enough_to_mean_something(self):
        """Two readings seconds apart prove nothing about a load in progress."""
        self.assertGreaterEqual(fr.STABILITY_GAP_MIN, 5)


class SharedSamplesTest(unittest.TestCase):
    """The samples are the whole day's, from every machine — not this one's.

    WHAT HAPPENED (2026-08-26, 21:03). The onboarding run for #alisei-b2b-sales
    ran on Lucy 1; the morning batch had run on Lucy 3. `_stability.json` lives
    under gitignored output/, so Lucy 1 opened with an empty history and held 5
    of 9 boards off a brand-new office's first thread — reporting "first sample
    of the day" at nine at night, about data that settled at 10:30 that morning
    (NDS 1,075, the very number it had just read).
    """

    EXTRACT = "tableau:tracker_nds"

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self._real_file = fr.STABILITY_FILE
        fr.STABILITY_FILE = tmp / "_stability.json"
        self.addCleanup(setattr, fr, "STABILITY_FILE", self._real_file)
        from automations.tableau_screenshots import stability_store as ss
        self.ss = ss
        # Stub the sheet: read_today serves what another machine "wrote", record
        # collects. No network, no credentials, no Mini Control workbook.
        self.shared = {}
        self.written = []
        real_read, real_record = ss.read_today, ss.record
        ss.read_today = lambda day: dict(self.shared)
        ss.record = lambda day, e, at, total: (
            self.written.append((e, at, total)),
            self.shared.setdefault(e, []).append([at, float(total)]))
        self.addCleanup(setattr, ss, "read_today", real_read)
        self.addCleanup(setattr, ss, "record", real_record)
        from automations.shared import tableau_patchright as tp
        csv = Path(tempfile.mkdtemp()) / "day.csv"
        csv.write_bytes(NDS_SHEET.encode("utf-16"))
        real_dl = tp.download_crosstab_patchright
        tp.download_crosstab_patchright = lambda *a, **k: csv
        self.addCleanup(setattr, tp, "download_crosstab_patchright", real_dl)

    def _check(self):
        return fr._check_stable_total(self.EXTRACT, fr.EXTRACTS[self.EXTRACT],
                                      TUE, WED)

    def test_another_machines_morning_sample_settles_this_run(self):
        """Lucy 3 sampled at 04:31; Lucy 1's evening run must see it."""
        self.shared[self.EXTRACT] = [["2026-08-26T04:31:00", 1075]]
        ok, why = self._check()
        self.assertTrue(ok, why)
        self.assertIn("finished loading", why)

    def test_a_growing_day_is_still_held_across_machines(self):
        """Sharing must not make the gate softer — 744 then 1,075 is loading."""
        self.shared[self.EXTRACT] = [["2026-08-26T04:31:00", 744]]
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("grew", why)

    def test_this_runs_sample_is_published_for_the_next_machine(self):
        self._check()
        self.assertEqual(1, len(self.written))
        self.assertEqual(self.EXTRACT, self.written[0][0])
        self.assertEqual(1075.0, self.written[0][2])

    def test_our_own_sample_is_not_double_counted(self):
        """We write to BOTH stores, so the shared read hands our own sample back.
        Counted twice it becomes 'two samples', and one reading of one moment
        would pass itself off as proof the number stopped moving."""
        ok, why = self._check()
        self.assertFalse(ok, why)
        self.assertIn("first sample", why)

    def test_an_unreachable_sheet_falls_back_to_local(self):
        """Best-effort: no shared history is the old behaviour, never a crash."""
        def boom(day):
            raise RuntimeError("no network")
        self.ss.read_today = boom
        ok, why = self._check()
        self.assertFalse(ok)
        self.assertIn("first sample", why)

    def test_bunched_samples_do_not_erase_an_older_proof(self):
        """Two machines probing at once are seconds apart. The verdict asks how
        long the number has READ THIS, not how far apart the last two rows are —
        the pairwise test called this 'only 0m apart' and held the board."""
        now = dt.datetime.now()
        self.shared[self.EXTRACT] = [
            ["2026-08-26T04:31:00", 1075],
            [(now - dt.timedelta(seconds=20)).isoformat(timespec="seconds"), 1075],
        ]
        ok, why = self._check()
        self.assertTrue(ok, why)
        self.assertIn("finished loading", why)


class MergeTest(unittest.TestCase):

    def test_duplicates_collapse(self):
        from automations.tableau_screenshots import stability_store as ss
        one = {"e": [["2026-08-26T04:31:00", 1075]]}
        self.assertEqual(1, len(ss.merge(one, one)["e"]))

    def test_result_is_oldest_first(self):
        from automations.tableau_screenshots import stability_store as ss
        got = ss.merge({"e": [["2026-08-26T10:30:00", 2]]},
                       {"e": [["2026-08-26T04:31:00", 1]]})
        self.assertEqual([1.0, 2.0], [v for _, v in got["e"]])

    def test_no_shared_history_is_just_the_local_series(self):
        from automations.tableau_screenshots import stability_store as ss
        local = {"e": [["2026-08-26T04:31:00", 1075]]}
        self.assertEqual(local, ss.merge(local, None))


class WiredUpTest(unittest.TestCase):

    def test_the_three_growing_families_use_stability(self):
        for eid in ("tableau:tracker_att", "tableau:tracker_nds",
                    "tableau:tracker_b2b"):
            with self.subTest(eid):
                self.assertIn("stable_total", fr.EXTRACTS[eid])

    def test_a_stable_verdict_is_never_cached(self):
        """Unlike a coverage date, 'it had settled' is a claim about a MOMENT —
        caching it would let 07:10's answer vouch for 04:11's capture."""
        import inspect
        src = inspect.getsource(fr._check_stable_total)
        self.assertNotIn("_record_ready", src)


if __name__ == "__main__":
    unittest.main()
