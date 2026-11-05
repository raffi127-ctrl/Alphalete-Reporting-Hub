"""python -m unittest automations.owner_sales_hourly.test_build"""
from __future__ import annotations

import datetime as dt
import types
import unittest

from automations.owner_sales_hourly import run

DAY = dt.date(2026, 10, 24)


def _office(owner, campaign="att"):
    return types.SimpleNamespace(owner=owner, campaign=campaign)


class OwnerTotals(unittest.TestCase):
    def test_sums_reps_and_merges_an_owners_two_offices(self):
        relay = {
            "carlos-b2batt": {DAY: {"A": {"Int": 3, "Int Up": 1, "DTV": 0, "NL": 0}}},
            "carlos": {DAY: {"B": {"Sales": 2, "Volume": 9}}},
        }
        offices = {"carlos-b2batt": _office("Carlos Hidalgo", "b2b_att"),
                   "carlos": _office("Carlos Hidalgo", "b2b_box")}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Carlos Hidalgo": 6})

    def test_campaign_keeps_only_that_campaigns_offices(self):
        relay = {
            "atef": {DAY: {"A": {"NL": 2}}},
            "atef-b2b": {DAY: {"B": {"Int": 5}}},
        }
        offices = {"atef": _office("Atef Choudhury", "nds"),
                   "atef-b2b": _office("Atef Choudhury", "b2b_att")}
        self.assertEqual(run.owner_totals(relay, offices, DAY, "nds"),
                         {"Atef Choudhury": 2})

    def test_office_with_no_reading_today_is_left_off_not_zero(self):
        relay = {"rashad": {DAY - dt.timedelta(days=9): {"A": {"Int": 4}}},
                 "steve": {DAY: {}}}
        offices = {"rashad": _office("Rashad Reed"),
                   "steve": _office("Steve McElwee")}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Steve McElwee": 0})

    def test_unknown_key_uses_fallback_name(self):
        relay = {"rafael_hidalgo": {DAY: {"A": {"Int": 2}}}}
        self.assertEqual(run.owner_totals(relay, {}, DAY),
                         {"Rafael Hidalgo": 2})

    def test_rafs_two_relay_keys_count_once(self):
        """Lucy 1's sweep relays him as rafael_hidalgo, his own MacBook as raf
        (2026-11-03): the 9:50 PM text showed 52 for a 26-sale day."""
        relay = {"rafael_hidalgo": {DAY: {"A": {"Int": 2}}},
                 "raf": {DAY: {"A": {"Int": 2}}}}
        offices = {"raf": _office("Rafael Hidalgo")}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Rafael Hidalgo": 2})
        # No reading from his machine today: the sweep's row still counts.
        relay = {"rafael_hidalgo": {DAY: {"A": {"Int": 2}}},
                 "raf": {dt.date(2026, 10, 23): {"A": {"Int": 9}}}}
        self.assertEqual(run.owner_totals(relay, offices, DAY),
                         {"Rafael Hidalgo": 2})


def _grid():
    hdr = ["", "", "Monday", "Tuesday", "RUNNING WEEK TOTALS"]
    return [
        ["ATT Fiber Team"] + hdr[1:],
        ["", "", "19", "20", ""],
        ["", "Jacob Dover", "1", "2", "3"],
        ["", "Ryan Mcspadden", "0", "1", "1"],
        ["Totals", "", "1", "3", "4"],
        [""],
        ["", "RAFAEL HIDALGO CAPTAINSHIP TEAM"],
        ["Fiber - All Units"] + hdr[1:],
        ["", "", "19", "20", ""],
        ["", "Trang Canavan", "1", "1", "2"],
        ["Totals", "", "1", "1", "2"],
    ]


class OnlyOrg(unittest.TestCase):
    def test_top_boxes_only_not_captainship_blocks(self):
        org = run.org_owners(_grid())
        self.assertEqual(org, {"jacob dover", "ryan mcspadden"})

    def test_case_and_alias_match_and_outsiders_dropped(self):
        org = run.org_owners(_grid(), {"Jacob Dover": ["Jake Dover"]})
        kept, dropped = run.only_org(
            {"Jake Dover": 4, "Ryan McSpadden": 2, "Trang Canavan": 9}, org)
        self.assertEqual(kept, {"Jake Dover": 4, "Ryan McSpadden": 2})
        self.assertEqual(dropped, ["Trang Canavan"])


class Text(unittest.TestCase):
    def test_sorted_desc_with_total(self):
        now = dt.datetime(2026, 10, 24, 17, 50)
        text = run.build_text({"B": 5, "A": 5, "C": 9}, now)
        self.assertEqual(text.splitlines(), [
            "Owner Sales Today - 5:50 PM CT", "",
            "1. C 9", "2. A 5", "3. B 5", "", "🏆 TOTAL: 19"])

    def test_not_in_total_is_ranked_but_not_counted(self):
        now = dt.datetime(2026, 11, 4, 17, 50)
        text = run.build_text({"Jairo Ruiz": 40, "Rafael Hidalgo": 26, "Drew Tepper": 27},
                              now, not_in_total=["rafael  hidalgo"])
        self.assertEqual(text.splitlines()[2:], [
            "1. Jairo Ruiz 40", "2. Drew Tepper 27", "3. Rafael Hidalgo 26",
            "", "🏆 TOTAL: 67"])

    def test_custom_title(self):
        now = dt.datetime(2026, 10, 24, 17, 50)
        text = run.build_text({"A": 1}, now, "NDS Sales Today")
        self.assertEqual(text.splitlines()[0], "NDS Sales Today - 5:50 PM CT")

    def test_window(self):
        self.assertTrue(run.in_window(dt.datetime(2026, 10, 24, 21, 50)))
        self.assertFalse(run.in_window(dt.datetime(2026, 10, 24, 9, 50)))
        self.assertFalse(run.in_window(dt.datetime(2026, 10, 25, 15, 50)))


class SouthShore(unittest.TestCase):
    def test_only_south_shore_owners_kept(self):
        totals = {"Jairo Ruiz": 35, "Colten Wright": 31, "Jacob Dover": 23,
                  "Drew Tepper": 22, "Eveliz Wright": 9}
        kept, _ = run.only_org(totals, run.south_shore_owners())
        self.assertEqual(kept, {"Jairo Ruiz": 35, "Colten Wright": 31,
                                "Drew Tepper": 22, "Eveliz Wright": 9})

    def test_alias_spelling_matches(self):
        sso = run.south_shore_owners({"Lizette Ruiz": ["Lizette Ruiz-Conejo"]})
        kept, _ = run.only_org({"Lizette Ruiz-Conejo": 4}, sso)
        self.assertEqual(kept, {"Lizette Ruiz-Conejo": 4})


class HalfHourPass(unittest.TestCase):
    def _at(self, minute):
        return dt.datetime(2026, 11, 4, 17, minute)

    def test_owners_chat_gets_both_passes(self):
        self.assertFalse(run.hourly_chat_skips("owners", self._at(15)))
        self.assertFalse(run.hourly_chat_skips("owners", self._at(45)))

    def test_other_chats_only_the_45(self):
        for chat in ("sso", "jairo"):
            self.assertTrue(run.hourly_chat_skips(chat, self._at(15)))
            self.assertFalse(run.hourly_chat_skips(chat, self._at(45)))

    def test_carlos_chat_only_the_15_so_it_starts_with_the_owners_chat(self):
        self.assertFalse(run.hourly_chat_skips("carlos", self._at(15)))
        self.assertTrue(run.hourly_chat_skips("carlos", self._at(45)))

    def test_carlos_title_and_chat(self):
        from automations.owner_sales_hourly import config as cfg
        self.assertEqual(cfg.CARLOS_GROUP, "ATT B2B Leaders")
        text = run.build_text({"A": 1}, dt.datetime(2026, 11, 5, 12, 15),
                              cfg.CARLOS_TITLE)
        self.assertEqual(text.splitlines()[0],
                         "Alphalete Owner Sales Today - 12:15 PM CT")

    def test_plist_fires_every_30_minutes_inside_the_window(self):
        import plistlib
        from pathlib import Path
        plist = Path(run.__file__).resolve().parents[2] / "deploy" / (
            "com.alphalete.owner-sales-hourly.plist")
        with plist.open("rb") as fh:
            slots = plistlib.load(fh)["StartCalendarInterval"]
        self.assertEqual({s["Minute"] for s in slots}, {15, 45})
        self.assertEqual(len(slots), 6 * 10 * 2)
        for s in slots:
            now = dt.datetime(2026, 11, 2 + s["Weekday"] - 1, s["Hour"], s["Minute"])
            self.assertTrue(run.in_window(now), now)


if __name__ == "__main__":
    unittest.main()
