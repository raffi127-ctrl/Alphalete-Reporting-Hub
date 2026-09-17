"""python -m unittest automations.weekly_knocks_focus.test_captainship_source

The --captainships source, offline: the OFFICE TOTALS it re-computes from Lucy
3's rows sidecar must be the row the weekly board itself draws, and a board
without its sidecar (or with no reps) is not a board.
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.captainship_drafts import config as CC
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions.test_teams import _rep
from automations.weekly_knocks_focus import box as BX
from automations.weekly_knocks_focus import run as R

SAT = dt.date(2026, 9, 12)


def _write(root: Path, captain: str, office: str, payload):
    d = root / f"knock_dispo_{captain}" / R._slug(office)
    d.mkdir(parents=True)
    png = d / f"weekly_knock_dispositions_{SAT.isoformat()}.png"
    png.write_bytes(b"png")
    if payload is not None:
        (d / f"rows_{png.stem}.json").write_text(json.dumps(payload),
                                                   encoding="utf-8")
    return png


class CaptainshipBoard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(CC, "RENDER_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_totals_are_the_boards_own_row(self):
        reps = [_rep("Ana Uno", talk=30, knocks=600),
                _rep("Beto Dos", talk=12, knocks=300)]
        png = _write(self.root, "pat", "John Richard Young",
                     {"ov_rows": reps, "apps": {"Ana Uno": 3}, "dispo_cols": []})
        data, got = R._captainship_board("John Richard Young", SAT)
        self.assertEqual(got, png)
        want = [r for r in B.compute_rows(reps, {"Ana Uno": 3}, [])
                if r[1] == B.TOTALS_LABEL]
        self.assertEqual(len(want), 1)
        want = want[0]
        self.assertEqual(data["totals"], want)
        self.assertEqual(data["headers"], B.headers_for([], False))
        # and it lands in the box like the Sunday file does
        from automations.weekly_knocks_focus.test_box import COL_B
        header, updates, _missing = BX.plan(data["headers"], data["totals"],
                                            COL_B)
        self.assertEqual(header, 46)
        by_label = {lab: v for _r, lab, v in updates}
        self.assertEqual(by_label["Mon-Fri Total Knocks"],
                         want[data["headers"].index("Mon–Fri Total Knocks")])

    def test_no_sidecar_or_no_reps_is_no_board(self):
        _write(self.root, "pat", "Eric Zech", None)
        self.assertEqual(R._captainship_board("Eric Zech", SAT), (None, None))
        _write(self.root, "tony", "Tony Chavez",
               {"ov_rows": [], "apps": None, "dispo_cols": []})
        self.assertEqual(R._captainship_board("Tony Chavez", SAT), (None, None))

    def test_other_week_is_not_found(self):
        _write(self.root, "pat", "Eric Zech",
               {"ov_rows": [_rep("Ana Uno")], "apps": None, "dispo_cols": []})
        self.assertEqual(R._captainship_board("Eric Zech", dt.date(2026, 9, 19)),
                         (None, None))


if __name__ == "__main__":
    unittest.main()
