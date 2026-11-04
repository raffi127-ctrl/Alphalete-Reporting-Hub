"""python -m unittest automations.alphalete_sales_board.test_lanes_job"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.alphalete_sales_board import lanes as L
from automations.recruiting_report import fill as RF
from automations.sales_board_fixer import lanes_check as LC
from automations.sales_board_fixer import run as FX

HEADS = ["Super Saiyan Lane 10+", "Exit Lane 0 - 3", "", "Super Saiyan Lane 10+",
         "Exit Lane 0 - 3", "", "2wks in a Row", "Raf's notes"]
TUE = "2026-11-03"
NEW, OLD, OLDER = "Sales Board WE 11.08", "Sales Board WE 11.01", "Sales Board WE 10.25"


def lane(tab, end):
    return "=iferror(FILTER('%s'!C4:C%d, '%s'!D4:D%d>=10),\"\")" % (tab, end, tab, end)


class WS:
    def __init__(self, title, values, formulas=None):
        self.title, self.values, self.formulas = title, values, formulas or values
        self.cells, self.batches = {}, []

    def get_values(self, **_):
        return self.values

    def get_all_values(self):
        return self.values

    def get(self, _rng, **_):
        return self.formulas

    def update_acell(self, a1, v):
        self.cells[a1] = v

    def batch_update(self, ups, **_):
        self.batches += ups


def board(title):
    return WS(title, [["", "", "Rep"]] * 3 + [["", "", "Ann"], ["", "", "TOTALS"]])


def lanes_tab(first="v", second="Last week"):
    banner = [first, "", "", second, "", "", "", ""]
    row = [lane(OLD, 79), lane(OLD, 79), "", lane(OLDER, 72), lane(OLDER, 72)]
    return WS("Lanes", [banner, HEADS, ["Ann"]], [banner, HEADS, row])


class Banner(unittest.TestCase):
    def test_typed_over_current(self):
        self.assertEqual(L.lost_banner([["v", "", "", "Last week"], HEADS]),
                         (0, 0, "Current Week"))

    def test_typed_over_last(self):
        self.assertEqual(L.lost_banner([["Current Week", "", "", ""], HEADS]),
                         (0, 3, "Last week"))

    def test_both_there_is_fine(self):
        self.assertIsNone(L.lost_banner([["Current Week", "", "", "Last week"], HEADS]))

    def test_both_gone_proves_nothing(self):
        self.assertIsNone(L.lost_banner([["v", "", "", "x"], HEADS]))

    def test_needs_lane_headers(self):
        self.assertIsNone(L.lost_banner([["v", "", "", "Last week"], ["A", "B", "", "C"]]))

    def test_fixer_puts_it_back(self):
        t = lanes_tab()
        found = LC.check(t.formulas, t.values, [[False] * 8] * 3, {}, None)
        hit = [x for x in found if x.kind == "lane_banner_lost"]
        self.assertEqual([(x.where, x.value) for x in hit], [("A1", "Current Week")])
        self.assertIn("lane_banner_lost", LC.REPAIRS)


class Job(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.told = Path(d.name) / "told.json"
        for p in (mock.patch.object(L, "TOLD_FILE", self.told),
                  mock.patch.object(L, "_heal_lost", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        dm = mock.patch.object(FX, "_dm_eve", return_value=True)
        self.dm = dm.start()
        self.addCleanup(dm.stop)

    def go(self, tabs, *args):
        book = mock.Mock()
        book.worksheets.return_value = tabs
        client = mock.Mock()
        client.open_by_key.return_value = book
        with mock.patch.object(RF, "_client", return_value=client):
            return L.main(["--date", TUE] + list(args))

    def test_banner_comes_back_and_lanes_roll(self):
        t = lanes_tab()
        self.assertEqual(self.go([t, board(NEW), board(OLD)], "--apply"), 0)
        self.assertEqual(t.cells, {"A1": "Current Week"})
        self.assertEqual(len(t.batches), 4)
        self.assertIn(NEW, t.batches[0]["values"][0][0])
        self.assertEqual(self.dm.call_count, 1)

    def test_preview_writes_and_tells_nothing(self):
        t = lanes_tab()
        self.go([t, board(NEW), board(OLD)])
        self.assertEqual((t.cells, t.batches, self.dm.call_count), ({}, [], 0))

    def test_stuck_tells_eve_once_a_day(self):
        t = lanes_tab("v", "x")                     # both banners gone
        for _ in range(3):
            self.assertEqual(self.go([t, board(NEW), board(OLD)], "--apply"), 2)
        self.assertEqual(self.dm.call_count, 1)
        self.assertIn("not updating", self.dm.call_args[0][0])

    def test_told_again_the_next_day(self):
        self.told.write_text(json.dumps({"date": "2026-11-02", "said": ["x"]}), encoding="utf-8")
        L._tell_eve("x", dt.date(2026, 11, 3))
        self.assertEqual(self.dm.call_count, 1)

    def test_missing_week_tab_tells_eve(self):
        self.assertEqual(self.go([lanes_tab(), board(OLD)], "--apply"), 0)
        self.assertIn("WE 11.8", self.dm.call_args[0][0])

    def test_failed_dm_is_not_remembered(self):
        self.dm.return_value = False
        L._tell_eve("x", dt.date(2026, 11, 3))
        self.assertFalse(self.told.exists())


if __name__ == "__main__":
    unittest.main()
