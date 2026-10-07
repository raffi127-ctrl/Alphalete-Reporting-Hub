"""NDS last-week backfill: a ticket closes only when the WEEK IS FULL.

    python -m unittest automations.alphalete_org_report.test_nds_lastweek_manifest

Sheets, the download and write_manifest are all mocked: a real clean manifest
closes the report's incident thread in Slack, and a test must never speak in
the channel.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.alphalete_org_report import nds_lastweek_fill as nf
from automations.shared import run_manifest

WEEK = dt.date(2026, 10, 4)
HEADER = ["", "", "WE 10/4"]


def _grid(new="", air="", heads="", rank=""):
    return [HEADER,
            ["", "New Lines", new],
            ["", "AIR", air],
            ["", "Active Selling Heads", heads],
            ["", "Scorecard Ranking", rank]]


class _WS:
    def __init__(self, title, grid):
        self.title, self.grid = title, grid

    def get_all_values(self):
        return self.grid


class _SH:
    def __init__(self, tabs):
        self.tabs, self.updates = tabs, []

    def worksheets(self):
        return self.tabs

    def values_batch_update(self, body):
        self.updates.append(body)


def _run(tabs, detail, dry_run=False):
    sh = _SH(tabs)
    with mock.patch.object(nf, "week_from_export", return_value=WEEK), \
            mock.patch.object(nf.opt_nds, "parse_tt_detail",
                              return_value=detail), \
            mock.patch.object(nf.opt_nds, "_norm_owner",
                              side_effect=lambda s: s.strip().lower()), \
            mock.patch.object(nf.rfill, "open_by_key", return_value=sh), \
            mock.patch.object(nf.rfill, "_retry", side_effect=lambda f: f()), \
            mock.patch.object(nf.rfill, "find_sunday_columns",
                              return_value={WEEK: 3}), \
            mock.patch.object(run_manifest, "write_manifest") as wm:
        res = nf.run("sheet", skip_download=True, dry_run=dry_run,
                     logfn=lambda *a: None)
    return res, wm, sh


FULL = {"phone": "10", "air_sold": "2", "rep_count": "5", "ranking": "7"}


class CompleteWeek(unittest.TestCase):
    def test_every_tab_full_is_delivered(self):
        res, wm, sh = _run([_WS("Ann Lee - NDS", _grid())], {"ann lee": FULL})
        self.assertEqual(res["holes"], [])
        self.assertEqual(res["cells"], 4)
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "nds_lastweek_fill")
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_already_full_week_is_delivered_with_zero_cells(self):
        res, wm, _ = _run([_WS("Ann Lee - NDS", _grid("1", "1", "1", "1"))],
                          {"ann lee": FULL})
        self.assertEqual(res["cells"], 0)
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_sara_filled_tab_off_the_tracker_counts_as_complete(self):
        res, wm, _ = _run([_WS("Bo Ray - NDS", _grid("1", "1", "1", "1"))],
                          {"someone else": FULL})
        self.assertEqual(res["complete"], ["Bo Ray - NDS"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])


class IncompleteWeek(unittest.TestCase):
    def test_tracker_gap_leaves_a_named_hole(self):
        rec = dict(FULL, air_sold="")
        res, wm, _ = _run([_WS("Ann Lee - NDS", _grid())], {"ann lee": rec})
        self.assertEqual(len(res["holes"]), 1)
        self.assertIn("AIR", res["holes"][0])
        self.assertIn("Ann Lee - NDS", wm.call_args.kwargs["failed"][0])

    def test_tab_off_the_tracker_with_blanks_is_a_hole(self):
        res, wm, _ = _run([_WS("Bo Ray - NDS", _grid())],
                          {"someone else": FULL})
        self.assertIn("not on the tracker", res["holes"][0])

    def test_missing_week_column_is_a_hole(self):
        sh = _SH([_WS("Ann Lee - NDS", _grid())])
        with mock.patch.object(nf, "week_from_export", return_value=WEEK), \
                mock.patch.object(nf.opt_nds, "parse_tt_detail",
                                  return_value={"ann lee": FULL}), \
                mock.patch.object(nf.opt_nds, "_norm_owner",
                                  side_effect=lambda s: s.strip().lower()), \
                mock.patch.object(nf.rfill, "open_by_key", return_value=sh), \
                mock.patch.object(nf.rfill, "_retry",
                                  side_effect=lambda f: f()), \
                mock.patch.object(nf.rfill, "find_sunday_columns",
                                  return_value={}), \
                mock.patch.object(run_manifest, "write_manifest") as wm2:
            res2 = nf.run("sheet", skip_download=True, logfn=lambda *a: None)
        self.assertIn("no 2026-10-04 column", res2["holes"][0])
        self.assertTrue(wm2.call_args.kwargs["failed"])


class NoProofOnDryRun(unittest.TestCase):
    def test_dry_run_writes_no_manifest(self):
        _res, wm, sh = _run([_WS("Ann Lee - NDS", _grid())], {"ann lee": FULL},
                            dry_run=True)
        wm.assert_not_called()
        self.assertEqual(sh.updates, [])

    def test_manifest_error_never_raises(self):
        with mock.patch.object(run_manifest, "write_manifest",
                               side_effect=OSError("disk")):
            nf.record_delivery(WEEK, [], [], 0, logfn=lambda *a: None)

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(nf.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(nf.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
