"""python -m unittest automations.weekly_knocks_focus.test_move_picture

2026-09-28: Michael Murphy's Production Breakdown grew into the row the
knocks picture sat on and wiped its =IMAGE; Eric Zech's picture block lost its
marker and =IMAGE but kept its (now empty) merge. The picture must move under
everything / take the empty block apart instead of failing or stacking."""
import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from automations.weekly_knocks_focus import run as R

SID = 7


class FakeSheet:
    def __init__(self, ws, merges):
        self.ws, self.merges, self.requests = ws, merges, []

    def fetch_sheet_metadata(self, params):
        if "ranges" in params:
            return {"sheets": [{"data": [{"columnMetadata": [], "rowMetadata": []}]}]}
        return {"sheets": [{"properties": {
            "sheetId": SID, "title": "T",
            "gridProperties": {"rowCount": 1000, "columnCount": 60,
                               "frozenColumnCount": 2}},
            "merges": self.merges}]}

    def batch_update(self, body):
        self.requests += body["requests"]


class FakeWS:
    id = SID
    title = "T"

    def __init__(self, values, merges):
        self.values = values
        self.spreadsheet = FakeSheet(self, merges)
        self.cleared, self.written = [], []

    def get_all_values(self):
        return self.values

    def batch_clear(self, ranges):
        self.cleared += ranges

    def batch_update(self, data, value_input_option=None):
        self.written += data


def _grid(n_rows, n_cols=60):
    return [[""] * n_cols for _ in range(n_rows)]


class MovePictureTest(unittest.TestCase):
    def _place(self, ws):
        with mock.patch.object(R, "_png", return_value=(b"x", 1200, 300)), \
                mock.patch.object(R, "_upload", return_value="FID"):
            return R._place_picture(ws, dt.date(2026, 9, 27), 15, Path("b.png"),
                                    live=True)

    def test_chart_grew_into_the_picture_row_moves_it_down(self):
        v = _grid(160)
        for r in range(130, 150):                  # chart rows 131..150, G..P
            v[r][6], v[r][7], v[r][15] = f"Rep {r}", "NEW INTERNET", "5"
        v[147][0] = "WEEKLY KNOCKS BOARD"          # marker on row 148
        v[147][1] = "Weekly Knock Dispositions — WE 9/20/26"
        ws = FakeWS(v, [])
        self.assertTrue(self._place(ws))
        a = {d["range"]: d["values"][0][0] for d in ws.written}
        self.assertEqual(a["A153"], "WEEKLY KNOCKS BOARD")   # 150 + 2 gap + 1
        self.assertIn("=IMAGE", a["O153"])
        self.assertEqual(sorted(ws.cleared), ["A148", "B148"])
        # the chart's own cells on row 148 are never cleared
        self.assertNotIn("G148", ws.cleared)

    def test_an_empty_leftover_block_is_unmerged_before_the_new_one(self):
        v = _grid(200)
        for r in range(130, 143):                  # chart ends row 143
            v[r][33] = "Rep"
        orphan = {"sheetId": SID, "startRowIndex": 143, "endRowIndex": 162,
                  "startColumnIndex": 14, "endColumnIndex": 30}
        ws = FakeWS(v, [orphan])
        self.assertTrue(self._place(ws))
        reqs = ws.spreadsheet.requests
        self.assertIn("unmergeCells", reqs[0])
        self.assertEqual(reqs[0]["unmergeCells"]["range"], orphan)
        self.assertIn("mergeCells", reqs[-1])

    def test_unchanged_spot_stays_put(self):
        v = _grid(160)
        for r in range(130, 140):
            v[r][6] = "Rep"
        v[142][0] = "WEEKLY KNOCKS BOARD"
        old = {"sheetId": SID, "startRowIndex": 142, "endRowIndex": 150,
               "startColumnIndex": 13, "endColumnIndex": 29}
        ws = FakeWS(v, [old])
        self.assertTrue(self._place(ws))
        a = {d["range"]: d["values"][0][0] for d in ws.written}
        self.assertEqual(a["A143"], "WEEKLY KNOCKS BOARD")
        self.assertEqual(ws.cleared, ["N143"])     # last week's =IMAGE only

    def test_chart_rows_beside_the_block_still_move_it(self):
        # Murphy 9/28 re-run: the chart reached the marker row but only in
        # columns left of the block — the picture still covered its tail.
        v = _grid(160)
        for r in range(130, 149):                  # chart rows 131..149, G..H
            v[r][6], v[r][7] = f"Rep {r}", "NEW INTERNET"
        v[147][0] = "WEEKLY KNOCKS BOARD"          # marker on row 148
        ws = FakeWS(v, [])
        self.assertTrue(self._place(ws))
        a = {d["range"]: d["values"][0][0] for d in ws.written}
        self.assertEqual(a["A152"], "WEEKLY KNOCKS BOARD")   # 149 + 2 gap + 1
        self.assertEqual(ws.cleared, ["A148"])


if __name__ == "__main__":
    unittest.main()
