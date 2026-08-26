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


# The real 8/26 line every AT&T/NDS/B2B view publishes — two fields run together
# with NO separator, which is what makes the segment bounding load-bearing.
RANGE_LINE = ("Last Server Update: 2026-08-26 08:11 ETData Source Sales Date "
              "Range: 2024-06-17  -  2026-08-25")

RANGE_FIELD = "Data Source Sales Date Range"


class DateRangeFormatTest(unittest.TestCase):
    """The AT&T / NDS / B2B pagers publish a RANGE in ISO, not a single US date."""

    def test_the_range_end_is_what_counts(self):
        """Coverage is where the data STOPS — the range start is 2024."""
        self.assertEqual(dt.date(2026, 8, 25),
                         fr.parse_last_update(RANGE_LINE, RANGE_FIELD))

    def test_a_neighbouring_field_is_not_borrowed(self):
        """'Last Server Update' abuts the next label with no separator. Read
        greedily it returns 8/25 (the range end); it must return 8/26."""
        self.assertEqual(dt.date(2026, 8, 26),
                         fr.parse_last_update(RANGE_LINE, "Last Server Update"))

    def test_the_server_stamp_is_not_what_we_gate_on(self):
        """A refresh can run on schedule and load nothing: on 8/26 the stamp said
        TODAY while coverage stopped yesterday. Gating on the stamp is a gate
        that passes every morning by construction."""
        stamp = fr.parse_last_update(RANGE_LINE, "Last Server Update")
        coverage = fr.parse_last_update(RANGE_LINE, RANGE_FIELD)
        self.assertGreater(stamp, coverage)
        for eid, cfg in fr.EXTRACTS.items():
            lu = cfg.get("last_update")
            if lu:
                self.assertNotIn("Server Update", lu["field"],
                                 "%s gates on the refresh stamp" % eid)


class EveryBoardIsGatedTest(unittest.TestCase):
    """After 8/26 all four tracker extracts read their OWN view's refresh sheet.

    The sheet names here are not guesses — each was listed by `--discover` and
    then pulled successfully. A typo would make the probe error every morning,
    and an always-erroring gate fail-opens, which is no gate at all."""

    EXPECTED = {
        "tableau:tracker_att": ("D2D1-PAGERV4", "Last Refresh (2)"),
        "tableau:tracker_nds": ("NDSDailyTracker", "zzz Last Refresh (5)"),
        "tableau:tracker_b2b": ("D2D1-PAGERV3", "Last Refresh (2)"),
        "tableau:tracker_quantum": ("LumenSalesTracker", "Last Update"),
    }

    def test_all_four_extracts_ask_the_workbook_directly(self):
        for eid, (view, sheet) in self.EXPECTED.items():
            with self.subTest(eid):
                lu = fr.EXTRACTS[eid].get("last_update")
                self.assertIsNotNone(lu, "%s still uses a stand-in crosstab" % eid)
                self.assertIn(view, lu["view_url"])
                self.assertEqual(sheet, lu["sheet"])

    def test_the_probe_reads_the_view_the_camera_shoots(self):
        """The old design's second hole: it probed a different view than the one
        it photographed. Each gated board's view must now appear in its probe."""
        from automations.tableau_screenshots import pages as pg
        for eid, cfg in fr.EXTRACTS.items():
            lu = cfg.get("last_update")
            if not lu:
                continue
            probed = lu["view_url"].split("/views/")[1].split("?")[0]
            board_views = [
                (pg.by_id(b) or {}).get("url", "").split("/views/")[-1].split("?")[0]
                for b in cfg["boards"]]
            self.assertTrue(
                any(v.split("/")[0] == probed.split("/")[0] for v in board_views),
                "%s probes a workbook none of its boards come from" % eid)

    def test_only_box_and_the_email_board_remain_ungated(self):
        self.assertEqual({"b2b_box", "vzftr"}, set(fr.UNGATED))


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


class WithholdStillBehindTest(unittest.TestCase):
    """Megan 2026-08-26: "the updated ones are sent and the non updated ones are
    reported in the slack channel and NOT sent."

    Before this, the ~7am catch-up posted whatever the morning had held, on the
    rule that a late board beats a missing one. That rule is right for Box, whose
    data genuinely lands at 7. It is wrong for a board nobody has refreshed: on
    8/26 it put a 0-sales quantum_fiber in front of 15 channels three hours after
    the gate had correctly held it."""

    def setUp(self):
        from automations.tableau_screenshots import run as _run
        from automations.tableau_screenshots import pages as pg
        self.run, self.pg = _run, pg

    def test_a_still_behind_board_is_dropped_from_the_send_set(self):
        selected = list(self.pg.PAGES)
        out = self.run.withhold_still_behind(selected, {"quantum_fiber": "behind"})
        self.assertNotIn("quantum_fiber", [p["id"] for p in out])

    def test_every_other_board_still_goes(self):
        """The updated ones are SENT — withholding one must not cost the rest."""
        selected = list(self.pg.PAGES)
        out = self.run.withhold_still_behind(selected, {"quantum_fiber": "behind"})
        self.assertEqual(len(selected) - 1, len(out))
        self.assertIn("b2b_box", [p["id"] for p in out])

    def test_nothing_behind_changes_nothing(self):
        selected = list(self.pg.PAGES)
        self.assertEqual([p["id"] for p in selected],
                         [p["id"] for p in
                          self.run.withhold_still_behind(selected, {})])

    def test_an_unknown_id_is_harmless(self):
        selected = list(self.pg.PAGES)
        out = self.run.withhold_still_behind(selected, {"no_such_board": "behind"})
        self.assertEqual(len(selected), len(out))

    def test_the_board_is_NOT_dropped_from_the_header(self):
        """The send set is trimmed; the header list is not. A withheld board has
        to stay visible with its note — 'reported in the slack channel' is half
        the instruction, and a silently absent board is the other failure."""
        from automations.tableau_screenshots import slack_post as sp
        self.pg.mark_late(["quantum_fiber"])
        self.addCleanup(self.pg.clear_runtime_late)
        header = sp.header_text(self.pg.PAGES, dt.date(2026, 8, 26),
                                pending_late=["quantum_fiber"],
                                note=sp.STALE_NOTICE)
        self.assertIn("ATT Quantum Fiber Daily Tracker", header)
        self.assertIn(sp.STALE_LATE_NOTE, header)
        self.assertIn(sp.STALE_NOTICE, header)


if __name__ == "__main__":
    unittest.main()
