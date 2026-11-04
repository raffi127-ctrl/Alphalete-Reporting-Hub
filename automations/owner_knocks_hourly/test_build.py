"""python -m unittest automations.owner_knocks_hourly.test_build"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from automations.owner_knocks_hourly import run as R

DAY = dt.date(2026, 10, 28)


def _rep(name, knocks, first="2:00 PM", last="7:00 PM"):
    return {"Rep": name, "Total Knocks": str(knocks),
            "Total Leads Knocked": str(knocks), "First Knock": first,
            "Last Knock": last}


def _row(key, reps, day="2026-10-28"):
    # Office, Day, Rows JSON, Tracker JSON, Count, Received, Local, Posted
    return [key, day, json.dumps(reps), "[]", str(len(reps)), "", "", ""]


OFFICES = {"khalil-nds": SimpleNamespace(owner="Khalil Mansour"),
           "khalil-att": SimpleNamespace(owner="Khalil Mansour"),
           "kash": SimpleNamespace(owner="Kash Rai"),
           "ryan": SimpleNamespace(owner="Ryan McSpadden", campaign="b2b_box"),
           "atef": SimpleNamespace(owner="Atef Choudhury", campaign="nds"),
           "atef-b2b": SimpleNamespace(owner="Atef Choudhury",
                                       campaign="b2b_att")}


class OwnerRowsTests(unittest.TestCase):
    def test_pools_an_owners_offices_and_keeps_only_the_day(self):
        values = [["hdr"],
                  _row("khalil-nds", [_rep("A", 100)]),
                  _row("khalil-att", [_rep("B", 50)]),
                  _row("kash", [_rep("C", 120)]),
                  _row("kash", [_rep("Old", 999)], day="2026-10-27")]
        got = R.owner_rows(values, OFFICES, DAY, skip_stale=False,
                           log=lambda *_: None)
        self.assertEqual(sorted(got), ["Kash Rai", "Khalil Mansour"])
        self.assertEqual(len(got["Khalil Mansour"]), 2)
        self.assertEqual([n for n, _ in R.ranked(got)],
                         ["Khalil Mansour", "Kash Rai"])   # 150 over 120

    def test_signature_moves_only_with_knocks(self):
        a = {"Kash Rai": [_rep("C", 120)]}
        b = {"Kash Rai": [_rep("C", 121)]}
        self.assertNotEqual(R.signature(a), R.signature(b))
        self.assertEqual(R.signature(a), R.signature({"Kash Rai": [_rep("C", 120)]}))


class SharedTabTests(unittest.TestCase):
    """Offices a Lucy pulls (Raf, Carlos NDS): the 'Lucy Knocks' tab."""

    def _book(self, values):
        ws = SimpleNamespace(get_all_values=lambda: values)
        return SimpleNamespace(worksheet=lambda name: ws)

    def test_fresh_today_counts_stale_or_old_day_does_not(self):
        from automations.owner_knocks_hourly import share
        now = dt.datetime.now()
        today = now.date().isoformat()
        values = [share.HEADER,
                  ["rafael", "Rafael Hidalgo", today,
                   now.isoformat(timespec="seconds"), json.dumps([_rep("R", 90)])],
                  ["carlos-nds", "Carlos Hidalgo", today,
                   (now - dt.timedelta(hours=2)).isoformat(timespec="seconds"),
                   json.dumps([_rep("C", 10)])],
                  ["x", "Jay Turnage", "2020-01-01",
                   now.isoformat(timespec="seconds"), json.dumps([_rep("J", 5)])]]
        got = share.read(self._book(values), now.date(), stale_minutes=45,
                         log=lambda *_: None)
        self.assertEqual(list(got), ["Rafael Hidalgo"])
        # A preview of a past day takes them all, whatever their age.
        got = share.read(self._book(values), now.date(), log=lambda *_: None)
        self.assertEqual(sorted(got), ["Carlos Hidalgo", "Rafael Hidalgo"])


class RenderTests(unittest.TestCase):
    def test_board_is_owner_lines_over_an_org_total(self):
        from automations.owner_knocks_hourly import config as cfg
        by_owner = {"Khalil Mansour": [_rep("A", 100), _rep("B", 50)],
                    "Kash Rai": [_rep("C", 120)]}
        with tempfile.TemporaryDirectory() as tmp:
            old = cfg.OUT_DIR
            cfg.OUT_DIR = Path(tmp)
            try:
                png = R.render(by_owner, DAY, dt.datetime(2026, 10, 28, 17, 20))
            finally:
                cfg.OUT_DIR = old
            self.assertTrue(Path(png).exists())

    def _table(self, by_owner, chan=None):
        """What the board would draw: its header, rows and draw options."""
        from automations.total_knocks import render as TR
        from automations.owner_knocks_hourly import config as cfg
        seen = {}

        def fake_draw(header, rows, title, theme, out_path, **kw):
            seen.update(header=header, rows=rows, kw=kw)
            return out_path
        real, TR._draw = TR._draw, fake_draw
        try:
            with tempfile.TemporaryDirectory() as tmp:
                old, cfg.OUT_DIR = cfg.OUT_DIR, Path(tmp)
                try:
                    R.render(by_owner, DAY, dt.datetime(2026, 10, 28, 17, 20),
                             chan)
                finally:
                    cfg.OUT_DIR = old
        finally:
            TR._draw = real
        return seen

    def test_chan_on_top_then_d2d_then_b2b_then_the_three_totals(self):
        values = [["hdr"],
                  _row("kash", [_rep("C", 120)]),
                  _row("khalil-nds", [_rep("A", 100)]),
                  _row("ryan", [_rep("B", 500)])]
        by_owner = R.owner_rows(values, OFFICES, DAY, skip_stale=False,
                                log=lambda *_: None)
        seen = self._table(by_owner, chan=[_rep("Z", 7)])
        self.assertEqual([r[1] for r in seen["rows"]],
                         ["CHAN PARK",
                          "D2D OWNERS", "KASH RAI", "KHALIL MANSOUR",
                          "B2B OWNERS", "RYAN MCSPADDEN",
                          "D2D TOTAL", "B2B TOTAL", "ORG TOTAL"])
        # Chan is in no total; each total only counts its own group.
        tk = seen["header"].index("Total Knocks")
        got = {r[1]: r[tk] for r in seen["rows"]}
        self.assertEqual((got["D2D TOTAL"], got["B2B TOTAL"], got["ORG TOTAL"]),
                         ("220", "500", "720"))
        self.assertEqual(sorted(seen["kw"]["section_rows"]), [0, 1, 4])

    def test_chan_and_the_strips_get_no_kpi_colours_owners_keep_them(self):
        seen = self._table(
            R.owner_rows([["hdr"], _row("kash", [_rep("C", 120, "1:00 PM")]),
                          _row("ryan", [_rep("B", 500, "1:00 PM")])],
                         OFFICES, DAY, skip_stale=False, log=lambda *_: None),
            chan=[_rep("Z", 7, "1:00 PM")])
        coloured = {r for r, _c in seen["kw"]["cell_bgs"]}
        self.assertEqual(coloured, {2, 4})   # Kash and Ryan, nobody else

    def test_one_group_only_has_no_subtotal(self):
        seen = self._table({"Kash Rai": [_rep("C", 120)]})
        self.assertEqual([r[1] for r in seen["rows"]],
                         ["D2D OWNERS", "KASH RAI", "ORG TOTAL"])

    def test_an_owner_on_both_gets_a_line_in_each_group(self):
        values = [["hdr"], _row("atef", [_rep("A", 10)]),
                  _row("atef-b2b", [_rep("B", 20)])]
        got = R.by_segment(R.owner_rows(values, OFFICES, DAY, skip_stale=False,
                                        log=lambda *_: None))
        self.assertEqual([(s, sum(len(v) for v in o.values())) for s, o in got],
                         [("D2D", 1), ("B2B", 1)])

    def test_times_on_the_offices_clock_so_zones_dont_move_the_average(self):
        """Omar's login is Central and his office Eastern (OV_CLOCK)."""
        omar = SimpleNamespace(owner="Omar Mohamad", key="omar",
                               timezone="America/New_York", campaign="att")
        raw = [{"rep": "O", "first knock": "12:30 PM", "last knock": "2:30 PM",
                "total knocks": "10", "total leads knocked": "10"}]
        got = R.owner_rows([["hdr"], _row("omar", raw)], {"omar": omar}, DAY,
                           skip_stale=False, log=lambda *_: None)
        self.assertEqual(got["Omar Mohamad"][0]["First Knock"], "1:30 PM")
        self.assertEqual(got["Omar Mohamad"][0]["Last Knock"], "3:30 PM")

    def test_shared_office_keeps_its_rows_beside_a_b2b_relay(self):
        everyone = {"Carlos Hidalgo": [dict(_rep("B", 5), _segment="B2B")],
                    "Raf": [dict(_rep("R", 5), _segment="D2D")]}
        R.add_shared(everyone, {"Carlos Hidalgo": [_rep("N", 9)],
                                "Raf": [_rep("dup", 99)]})
        self.assertEqual(len(everyone["Carlos Hidalgo"]), 2)
        self.assertEqual(len(everyone["Raf"]), 1)   # never counted twice


class ChanPullTests(unittest.TestCase):
    def _pull(self, result):
        from automations.rashad_metrics import knocks_pull as KP
        calls = []

        def fake(jobs, **kw):
            calls.append((jobs, kw))
            if isinstance(result, Exception):
                raise result
            return result
        real, KP.pull_offices_days = KP.pull_offices_days, fake
        try:
            return R.chan_rows(DAY, log=lambda *_: None), calls
        finally:
            KP.pull_offices_days = real

    def test_his_rows_come_back_and_the_campaign_is_pinned(self):
        rows = [_rep("Z", 7)]
        got, calls = self._pull([("Chan Park", {DAY: rows}, None)])
        self.assertEqual(got, rows)
        self.assertEqual(calls[0][0][0][1], [DAY])
        self.assertEqual(len(calls[0][0][0]), 3)

    def test_a_failed_or_empty_pull_only_loses_the_line(self):
        self.assertIsNone(self._pull(RuntimeError("busy"))[0])
        self.assertIsNone(self._pull([("Chan Park", {}, ValueError("x"))])[0])
        self.assertIsNone(self._pull([("Chan Park", {DAY: []}, None)])[0])


if __name__ == "__main__":
    unittest.main()
