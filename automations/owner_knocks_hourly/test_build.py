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
           "kash": SimpleNamespace(owner="Kash Rai")}


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

    def test_zone_totals_east_to_west_and_none_for_one_zone(self):
        by_owner = {"Khalil Mansour": [_rep("A", 100)],
                    "Colten Wright": [_rep("B", 50)],
                    "Rafael Hidalgo": [_rep("C", 70)]}
        zones = {"Khalil Mansour": "America/Chicago",
                 "Colten Wright": "America/New_York"}
        got = R.zone_totals(by_owner, zones)
        # Raf has no office row -> Central with Khalil.
        self.assertEqual([(n, len(rows)) for n, rows in got],
                         [("EASTERN TOTAL", 1), ("CENTRAL TOTAL", 2)])
        self.assertEqual(R.zone_totals({"Khalil Mansour": [_rep("A", 1)]},
                                       zones), [])


if __name__ == "__main__":
    unittest.main()
