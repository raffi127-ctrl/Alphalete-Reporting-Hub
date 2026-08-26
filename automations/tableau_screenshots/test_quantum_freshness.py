"""Gate the Quantum Fiber board on the date its own workbook publishes.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_quantum_freshness

WHAT HAPPENED (2026-08-26). quantum_fiber was the one board with NO freshness
gate — nothing else in the repo reads RES-LumenSalesTrackervMZ, so there was no
verified worksheet to probe and wiring a guess would have made a permanently
erroring gate. That morning it went to 15 channels showing Tuesday = 0 sales,
-100% against both its own baselines, while its 6-week history had Tuesdays of
164/205/171/175/172/178. Not a bad day: an unloaded one.

The workbook had been saying so the whole time. Its "Last Update" sheet reads:

    Last SFDC Object Update: 8/25/2026 | Latest Activities Data Update: 8/24/2026

Activities — the board's actual numbers — reached only 8/24, and the completed
day we needed was 8/25. Nothing read that sheet.

So this gate does not infer freshness from whether some row carries yesterday's
date (what the other three extracts must do, and what cannot tell a half-loaded
day from a finished one). It asks the workbook which day it reaches.

WHICH FIELD IS LOAD-BEARING. The two dates do not move together, and on the
morning that failed they differed by exactly the day in question: gating on
"Last SFDC Object Update" (8/25) would have passed 8/26 clean. That is why the
field is named in config and asserted here.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.tableau_screenshots import freshness as fr


# The real 8/26 export, byte-for-byte after decoding.
LIVE_LINE = ("Last SFDC Object Update: 8/25/2026 | "
             "Latest Activities Data Update: 8/24/2026\n")

ACTIVITIES = "Latest Activities Data Update"
SFDC = "Last SFDC Object Update"


class ParseLastUpdateTest(unittest.TestCase):

    def test_it_reads_the_activities_date_off_the_live_line(self):
        self.assertEqual(dt.date(2026, 8, 24),
                         fr.parse_last_update(LIVE_LINE, ACTIVITIES))

    def test_the_two_fields_are_told_apart(self):
        """They differed by a day on the morning this was built — a parser that
        grabs 'the first date on the line' passes the failure."""
        self.assertEqual(dt.date(2026, 8, 25),
                         fr.parse_last_update(LIVE_LINE, SFDC))

    def test_a_missing_field_is_none_not_a_crash(self):
        self.assertIsNone(fr.parse_last_update(LIVE_LINE, "Nonexistent Field"))
        self.assertIsNone(fr.parse_last_update("", ACTIVITIES))

    def test_an_impossible_date_is_none(self):
        self.assertIsNone(fr.parse_last_update(
            "Latest Activities Data Update: 13/45/2026", ACTIVITIES))

    def test_utf16_is_decoded(self):
        """Tableau sends these crosstabs as UTF-16 with a BOM; read as utf-8 the
        whole line is mojibake and every field 'goes missing'."""
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as fh:
            fh.write(LIVE_LINE.encode("utf-16"))
            path = Path(fh.name)
        self.addCleanup(path.unlink)
        text = fr._read_crosstab_text(path)
        self.assertEqual(dt.date(2026, 8, 24),
                         fr.parse_last_update(text, ACTIVITIES))


class QuantumGateVerdictTest(unittest.TestCase):
    """The verdict itself, with the download stubbed — no Tableau in a test."""

    EXTRACT = "tableau:tracker_quantum"

    def _stub_download(self, text: str):
        import tempfile
        from pathlib import Path
        from automations.shared import tableau_patchright as tp
        tmp = Path(tempfile.mkdtemp()) / "last_update.csv"
        tmp.write_bytes(text.encode("utf-16"))
        real = tp.download_crosstab_patchright
        tp.download_crosstab_patchright = (
            lambda *a, **k: tmp)
        self.addCleanup(setattr, tp, "download_crosstab_patchright", real)

    def test_the_morning_that_failed_would_have_been_held(self):
        self._stub_download(LIVE_LINE)
        cfg = fr.EXTRACTS[self.EXTRACT]
        ok, why = fr._check_last_update(self.EXTRACT, cfg, dt.date(2026, 8, 25))
        self.assertFalse(ok, "8/24 data on a day needing 8/25 must be held")
        self.assertIn("not refreshed", why,
                      "stale_boards only holds on a 'not refreshed' verdict")

    def test_a_caught_up_workbook_passes(self):
        self._stub_download("Latest Activities Data Update: 8/25/2026\n")
        cfg = fr.EXTRACTS[self.EXTRACT]
        ok, why = fr._check_last_update(self.EXTRACT, cfg, dt.date(2026, 8, 25))
        self.assertTrue(ok, why)

    def test_an_unreadable_sheet_never_holds_the_board(self):
        """Standing rule here: a probe that cannot read must not hold a board
        that might be perfectly fine."""
        self._stub_download("some other wording entirely\n")
        cfg = fr.EXTRACTS[self.EXTRACT]
        ok, why = fr._check_last_update(self.EXTRACT, cfg, dt.date(2026, 8, 25))
        self.assertTrue(ok)
        self.assertIn("not held", why)

    def test_a_pull_failure_never_holds_the_board(self):
        from automations.shared import tableau_patchright as tp

        def boom(*a, **k):
            raise RuntimeError("tableau flaked")
        real = tp.download_crosstab_patchright
        tp.download_crosstab_patchright = boom
        self.addCleanup(setattr, tp, "download_crosstab_patchright", real)
        cfg = fr.EXTRACTS[self.EXTRACT]
        ok, why = fr._check_last_update(self.EXTRACT, cfg, dt.date(2026, 8, 25))
        self.assertTrue(ok)
        self.assertIn("not held", why)


class QuantumIsWiredInTest(unittest.TestCase):

    def test_quantum_fiber_is_no_longer_listed_as_ungated(self):
        self.assertNotIn("quantum_fiber", fr.UNGATED)

    def test_the_board_resolves_to_the_new_extract(self):
        self.assertEqual(["tableau:tracker_quantum"],
                         fr.extracts_for_boards(["quantum_fiber"]))

    def test_the_gate_reads_activities_not_sfdc(self):
        """The whole point. Config must name the field that was behind."""
        self.assertEqual(
            ACTIVITIES,
            fr.EXTRACTS["tableau:tracker_quantum"]["last_update"]["field"])


if __name__ == "__main__":
    unittest.main()
