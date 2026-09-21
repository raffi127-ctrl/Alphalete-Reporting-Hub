"""The run manifest is the proof of delivery the ticket closer looks for
(shared/delivery_check). Written only when the PROD board really is current.

No browser, no Sheet, no Slack: a fake workbook and a tiny order-log CSV.

    python -m unittest automations.rep_sales_fill.test_manifest
"""
import argparse
import datetime as dt
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from automations.rep_sales_fill import run as R
from automations.rep_sales_fill.test_road_trip import grid, log
from automations.shared import run_manifest
from automations.shared import section_drop_alert

MON = dt.date(2026, 9, 14)             # a closed week: nothing here is "today"
SUN = dt.date(2026, 9, 20)


class _Ws:
    title = "Sales Board WE 9.20"

    def __init__(self, g):
        self.g, self.writes = g, []

    def get_all_values(self):
        return self.g

    def batch_update(self, body, **_kw):
        self.writes.extend(body)


def _args(**kw):
    base = dict(sheet_id=None, preview=False, apply=True, overwrite=False,
                from_file=None)
    base.update(kw)
    return argparse.Namespace(**base)


class Manifest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = log([["Andrew Sanborn", "9/14/2026", "NEW INTERNET"]])
        # Nothing may reach the channel from a test.
        for p in (mock.patch.object(run_manifest, "MANIFEST_DIR", self.tmp),
                  mock.patch.object(section_drop_alert, "resolved"),
                  mock.patch.object(section_drop_alert, "alert")):
            p.start()
            self.addCleanup(p.stop)

    def run_rt(self, g, **kw):
        ws = _Ws(g)
        ss = types.SimpleNamespace(title="Alphalete SALES BOARD 2025")
        capture = types.ModuleType("automations.alphalete_production.capture")
        capture.SHEET_ID, capture.find_week_tab = "prod", lambda _ss, _d: ws
        fill = types.ModuleType("automations.recruiting_report.fill")
        fill.open_by_key = lambda _k: ss
        fill._retry = lambda fn, *a, **k: fn(*a, **k)

        def _no_form():
            raise RuntimeError("no form in a test")
        fill._client = _no_form
        with mock.patch.dict(sys.modules, {
                "automations.alphalete_production.capture": capture,
                "automations.recruiting_report.fill": fill}):
            rc = R.run_rt(_args(from_file=str(self.src), **kw), MON, SUN)
        return rc, ws

    def manifest(self):
        p = self.tmp / "rep_sales_fill.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def test_real_write_records_delivery(self):
        rc, ws = self.run_rt(grid())
        self.assertEqual(rc, 0)
        self.assertTrue(ws.writes)
        m = self.manifest()
        self.assertIsNotNone(m)
        self.assertTrue(m["ok"])
        self.assertEqual(m["failed"], [])

    def test_board_already_current_is_a_delivery(self):
        rc, _ws = self.run_rt(grid())               # first pass fills it
        g = grid()
        g[3][3] = "1"                                # Andrew, Monday Int = 1
        (self.tmp / "rep_sales_fill.json").unlink()
        rc, ws = self.run_rt(g)
        self.assertEqual(rc, 0)
        self.assertEqual(ws.writes, [])
        self.assertIsNotNone(self.manifest())

    def test_preview_writes_no_manifest(self):
        for kw in (dict(apply=False), dict(preview=True),
                   dict(sheet_id="a-copy")):
            rc, _ws = self.run_rt(grid(), **kw)
            self.assertEqual(rc, 0)
            self.assertIsNone(self.manifest(), kw)

    def test_hold_writes_no_manifest(self):
        self.src = log([["Andrew Sanborn", "9/15/2026", "NEW INTERNET"]])
        rc, _ws = self.run_rt(grid())               # Monday not published yet
        self.assertEqual(rc, 75)
        self.assertIsNone(self.manifest())


if __name__ == "__main__":
    unittest.main()
