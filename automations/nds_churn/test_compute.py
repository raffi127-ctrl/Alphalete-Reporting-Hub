"""nds_churn math over a synthetic NDS-SN export (long-format, Carlos's
owner + a stranger's row)."""
import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.nds_churn import comp
from automations.nds_churn import compute as C

TODAY = dt.date(2026, 11, 9)
HEADER = ["Owner & Office", "Rep", "Customer Name", "sp.Order Date (copy)",
          "sp.SPM Number", "spe.Account BAN", "Product Type (Broken Out)",
          "DTR Status (enriched)", "DTR Status Date",
          "Activatoin Date (order log)", "spe.Name", "spe.TN", "spe.TN Type",
          "Package", "Ported From", "Disconnect Reason (Consolidated)",
          "Measure Names", "Measure Values"]


def _row(rep, cust, od, spm, ban, prod, status, sdate, posted, spe, tn,
         tntype, pkg, ported, reason, owner="CARLOS HIDALGO\nAlphalete"):
    return [owner, rep, cust, od, spm, ban, prod, status, sdate, posted, spe,
            tn, tntype, pkg, ported, reason, "Unit Count", "1"]


ROWS = [
    _row("Nick Smedra", "HENRY W", "10/20/2026", "DSI1", "BAN1", "WIRELESS",
         "Posted", "", "10/25/2026", "SPE1", "111", "port", "iPhone 18", "Verizon", ""),
    _row("Nick Smedra", "HENRY W", "10/20/2026", "DSI1", "BAN1", "WIRELESS",
         "Disconnected", "11/3/2026", "10/25/2026", "SPE2", "222", "port",
         "BYOD Unlimited", "Verizon", "Non-Pay"),
    _row("Andrew Park", "MARIA G", "10/28/2026", "DSI2", "BAN2", "AIR",
         "Posted", "", "11/1/2026", "SPE3", "", "", "Internet Air", "", ""),
    _row("Andrew Park", "OLD O", "9/1/2026", "DSI3", "BAN3", "WIRELESS",
         "Disconnected", "9/20/2026", "9/5/2026", "SPE4", "444", "port",
         "iPhone", "T-Mobile", "Buyer's Remorse"),
    _row("Andrew Park", "PEND P", "11/5/2026", "DSI4", "BAN4", "WIRELESS",
         "Shipped", "", "", "SPE5", "555", "new", "iPhone", "", ""),
    # an activated upgrade and a tablet 'new' line: in the window, NOT churn base
    _row("Andrew Park", "UPG U", "10/26/2026", "DSI5", "BAN5", "WIRELESS",
         "Posted", "", "10/28/2026", "SPE6", "666", "upgrade", "iPhone 18", "", ""),
    _row("Andrew Park", "TAB T", "10/26/2026", "DSI6", "BAN6", "WIRELESS",
         "Disconnected", "11/1/2026", "10/28/2026", "SPE7", "777", "new",
         "Galaxy Tab A11+", "", ""),
    # a PORTED iPad: TN type says port, the device says tablet -> not churn base
    _row("Andrew Park", "PAD P", "10/26/2026", "DSI7", "BAN7", "WIRELESS",
         "Posted", "", "10/28/2026", "SPE8", "888", "port", "iPad (A16) A335", "Verizon", ""),
    _row("Someone Else", "NOT MINE", "11/1/2026", "DSI9", "BAN9", "WIRELESS",
         "Disconnected", "11/5/2026", "11/2/2026", "SPE9", "999", "port",
         "BYOD", "AT&T", "Non-Pay", owner="KHALIL MANSOUR\nOffice"),
]
# a second measure row for SPE1 -- must collapse away
ROWS.append(list(ROWS[0]))
ROWS[-1][16], ROWS[-1][17] = "Revenue", "213"


class Compute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = Path(tempfile.mkdtemp())
        cls.csv = d / "nds_orderlog.csv"
        with open(cls.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["noise", "line"])
            w.writerow(HEADER)
            w.writerows(ROWS)
        cls.header, cls.ix, cls.lines = C.load_owner_lines(cls.csv, log=lambda *_: None)

    def test_load_filters_owner_and_collapses_measures(self):
        self.assertEqual(len(self.lines), 8)
        self.assertEqual(self.ix["reason"], 15)
        self.assertEqual(self.header[self.ix["status"]], "DTR Status (enriched)")
        self.assertEqual(self.header[self.ix["status_date"]], "DTR Status Date")

    def test_churn_summary(self):
        s = C.churn_summary(self.lines, TODAY)
        self.assertEqual(s["base"], {"Wireless": 2, "Air": 1, "Internet": 0})
        self.assertEqual(s["disc"], {"Wireless": 1, "Air": 0, "Internet": 0})
        self.assertEqual(s["split"]["byod"], {"base": 1, "disc": 1})
        self.assertEqual(s["split"]["non_byod"], {"base": 1, "disc": 0})
        self.assertEqual(s["excluded"], {"upgrade": 1, "new": 1, "device": 1})

    def test_rolloff_groups_and_tables(self):
        groups = C.rolloff_groups(self.lines, TODAY)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual((g["cls"], g["customer"], g["lines"], g["days_left"]),
                         ("byod", "HENRY W", 1, 15))
        self.assertEqual(g["falloff"], dt.date(2026, 11, 24))      # posted 10/25 + 30
        self.assertEqual(g["disc_date"], dt.date(2026, 11, 3))     # real disconnect date
        self.assertEqual((g["kind"], g["acct_lines"], g["device"], g["product"]),
                         ("port", "2 (2W)", "BYOD", "Wireless"))    # kind, not CRU/IRU
        tables = C.class_tables(self.lines, TODAY)
        self.assertEqual([t["cls"] for t in tables], ["wireless", "byod", "air"])
        self.assertEqual([t["title"] for t in tables],
                         ["ALL WIRELESS (non-BYOD)", "BYODs", "AIR"])
        w, b, air = tables
        self.assertEqual((w["act"], w["disc"], w["pct"], w["rows"]), (1, 0, 0.0, []))
        self.assertEqual((b["act"], b["disc"], b["pct"]), (1, 1, 100.0))
        self.assertEqual(b["rows"], [["15d", "11/24/2026", 1, 0.0, 0.0, "HENRY W", "Nick Smedra",
                                      "10/20/2026", "10/25/2026", "11/3/2026", "port", "2 (2W)",
                                      "BYOD", "Wireless"]])
        self.assertEqual(len(b["rows"][0]), 14)
        self.assertEqual((air["act"], air["disc"], air["rows"]), (1, 0, []))

    def test_class_tables_follow_box(self):
        # Carlos 2026-11-15: one table per box row -- every box-row
        # disconnect (not just ports) under its own table, soonest fall-off
        # first; each row's two churn-after numbers divide by the box.
        byod = next(l for l in self.lines if l["customer"] == "HENRY W" and l["byod"])
        late = dict(byod, customer="LATE L", ban="BAN8", spe="SPE12", tn="1212",
                    posted=dt.date(2026, 10, 30), status_date_d=dt.date(2026, 11, 5))
        air = dict(next(l for l in self.lines if l["customer"] == "MARIA G"),
                   customer="EARLY A", ban="BAN9", spe="SPE13", status="Disconnected",
                   posted=dt.date(2026, 10, 20), status_date_d=dt.date(2026, 11, 2))
        phone = dict(byod, customer="NEW N", ban="BAN10", spe="SPE14", tn="1414",
                     package="Unlimited", device="iPhone 18 Pro - 256GB - Black",
                     byod=False, tn_type="new", posted=dt.date(2026, 10, 28),
                     status_date_d=dt.date(2026, 11, 4))
        lines = list(self.lines) + [late, air, phone]
        groups = C.rolloff_groups(lines, TODAY)
        self.assertEqual([(g["customer"], g["cls"]) for g in groups],
                         [("EARLY A", "air"), ("HENRY W", "byod"),
                          ("NEW N", "wireless"), ("LATE L", "byod")])
        box = C.product_box(lines, TODAY)
        self.assertEqual(box["all_orders"], {"act": 6, "disc": 4, "pend": 1})
        w, b, a = C.class_tables(lines, TODAY, box)
        self.assertEqual([r[C.T_CUSTOMER] for r in w["rows"]], ["NEW N"])
        self.assertEqual([r[C.T_CUSTOMER] for r in b["rows"]], ["HENRY W", "LATE L"])
        self.assertEqual([r[C.T_CUSTOMER] for r in a["rows"]], ["EARLY A"])
        for t in (w, b, a):                      # each table = its box row's disconnects
            self.assertEqual(sum(r[C.T_LINES] for r in t["rows"]), box[t["cls"]]["disc"])
        self.assertEqual(w["rows"][0][10], "new")           # a new-number phone is listed too
        # % after rolloff: All Orders over B5 (6 activations), own over the table's row
        self.assertAlmostEqual(w["rows"][0][C.T_ALL_PCT], 1 / 6)   # LATE L (11/29) is later
        self.assertEqual(w["rows"][0][C.T_OWN_PCT], 0.0)
        self.assertAlmostEqual(b["rows"][0][C.T_ALL_PCT], 2 / 6)   # NEW N + LATE L after 11/24
        self.assertEqual(b["rows"][0][C.T_OWN_PCT], 0.5)           # LATE L of 2 BYOD activations
        self.assertEqual((b["rows"][1][C.T_ALL_PCT], b["rows"][1][C.T_OWN_PCT]), (0.0, 0.0))
        self.assertEqual((a["rows"][0][C.T_ALL_PCT], a["rows"][0][C.T_OWN_PCT]), (0.5, 0.0))
        self.assertEqual((b["disc"], b["act"], b["pct"]), (2, 2, 100.0))
        self.assertIsNone(C.pct_after(groups, ("internet",), TODAY, 0))

    def test_box_activation_rates(self):
        r = C.box_activation_rates(self.lines, TODAY)
        self.assertEqual(r["wireless"]["0-30"], {"activated": 1, "sold": 2, "rate": 0.5})
        self.assertEqual(r["byod"]["0-30"], {"activated": 1, "sold": 1, "rate": 1.0})
        self.assertEqual(r["air"]["0-30"], {"activated": 1, "sold": 1, "rate": 1.0})
        self.assertEqual(r["internet"]["0-30"], {"activated": 0, "sold": 0, "rate": None})
        self.assertEqual(r["all_orders"]["0-30"], {"activated": 3, "sold": 4, "rate": 0.75})
        self.assertIsNone(r["all_orders"]["31-60"]["rate"])
        office, _ = C.activation_rates(self.lines, TODAY)   # no Internet in the fixture
        self.assertEqual(office["0-30"]["sold"], r["all_orders"]["0-30"]["sold"])

    def test_recent_highlight_follows_the_disconnect_column(self):
        from automations.nds_churn import sheet as S
        formula, ranges = S.recent_highlight_spec(7)
        # Disconnect Date is the 10th shown column (J); the rule must name it,
        # not the $H the B2B tab's copy carried.
        self.assertEqual(S.LIST_HEADERS[9], "Disconnect Date")
        self.assertEqual(formula, '=AND($J16<>"",TODAY()-$J16>=0,TODAY()-$J16<=7)')
        # the whole tables region, A16:N98, half-open
        self.assertEqual(ranges, [{"sheetId": 7, "startRowIndex": 15, "endRowIndex": 98,
                                   "startColumnIndex": 0, "endColumnIndex": 14}])
        self.assertEqual(S._norm_range({"sheetId": 7, "startRowIndex": 15, "endRowIndex": 98,
                                        "endColumnIndex": 14}),
                         S._norm_range(ranges[0]))

    def test_table_layout_and_grid(self):
        from automations.nds_churn import sheet as S

        def t(cls, n, act=10, disc=2):
            return {"cls": cls, "title": C.TABLE_TITLES[cls], "act": act, "disc": disc,
                    "pct": 100.0 * disc / act if act else None,
                    "rows": [[f"{i}d", "11/20/2026", 1, 0.1, None, f"C{i}", "Rep", "11/1/2026",
                              "11/2/2026", "11/3/2026", "port · OOF", "1 (1W)", "BYOD", "Wireless"]
                             for i in range(n)]}
        tables = [t("wireless", 2), t("byod", 0, act=0, disc=0), t("air", 1, act=4, disc=1)]
        layout = S.table_layout(tables)
        self.assertEqual(layout, [
            {"band": 15, "header": 16, "first": 17, "last": 18, "n": 2},
            {"band": 20, "header": 21, "first": 22, "last": 22, "n": 1},
            {"band": 24, "header": 25, "first": 26, "last": 26, "n": 1}])
        self.assertEqual(S.tables_end_row(layout), 26)
        grid = S.tables_grid(tables, layout)
        self.assertEqual(len(grid), 26 - 15 + 1)
        self.assertEqual(grid[0][0], "ALL WIRELESS (non-BYOD) — 2 of 10 disconnected = 20.00%")
        self.assertEqual(grid[1][4], "All Wireless % After Rolloff")
        self.assertEqual(grid[2][4], "")                       # None -> blank cell
        self.assertEqual(grid[5][0], "BYODs — no activations in the last 30 days")
        self.assertEqual(grid[6][4], "BYODs % After Rolloff")
        self.assertEqual(grid[7][0], S.NO_ROWS_TEXT)
        self.assertEqual(grid[9][0], "AIR — 1 of 4 disconnected = 25.00%")
        self.assertEqual(grid[10][4], "Air % After Rolloff")
        self.assertTrue(all(len(r) == 14 for r in grid))
        self.assertEqual(S.table_headers("wireless"), S.LIST_HEADERS)
        reqs = S.table_format_requests(3, layout)
        self.assertEqual(reqs[0]["repeatCell"]["range"],
                         {"sheetId": 3, "startRowIndex": 14, "endRowIndex": 98,
                          "startColumnIndex": 0, "endColumnIndex": 14})
        ph = S.placeholder_requests(3, layout, tables)
        self.assertEqual(len(ph), 1)
        self.assertEqual(ph[0]["repeatCell"]["range"]["startRowIndex"], 21)   # row 22

    def test_pending_orders(self):
        # PEND P: sold 11/5, Shipped -> the one pending line; everything else
        # in the window is Posted / Disconnected (activated), OLD O is 9/1.
        p = C.pending_orders(self.lines, TODAY)
        self.assertEqual((p["Wireless"], p["Air"], p["Internet"], p["Other"]),
                         (1, 0, 0, 0))
        # excluded = UPG U + TAB T + PAD P (sold in the window, not orders)
        self.assertEqual((p["total"], p["canceled"], p["excluded"]), (1, 0, 3))
        self.assertEqual(p["statuses"], {"Shipped": 1})
        # a pending tablet is not a pending order
        tab = dict(next(l for l in self.lines if l["customer"] == "PEND P"))
        tab.update({"device": "Galaxy Tab A11+", "spe": "SPE11", "tn": "1111"})
        p1 = C.pending_orders(list(self.lines) + [tab], TODAY)
        self.assertEqual((p1["total"], p1["excluded"]), (1, 4))
        # a canceled line is neither pending nor activated: counted apart
        extra = dict(next(l for l in self.lines if l["customer"] == "PEND P"))
        extra.update({"status": "Canceled", "spe": "SPE10", "tn": "1010"})
        p2 = C.pending_orders(list(self.lines) + [extra], TODAY)
        self.assertEqual((p2["total"], p2["canceled"]), (1, 1))
        # ties out with the activation bucket: sold = activated + pending + canceled
        office, _ = C.activation_rates(list(self.lines) + [extra], TODAY)
        self.assertEqual(office["0-30"]["sold"],
                         office["0-30"]["activated"] + p2["total"] + p2["canceled"])

    def test_activation_rates(self):
        # Carlos 2026-11-10: tablets, watches and upgrades are not orders --
        # UPG U (upgrade), TAB T (Galaxy Tab) and PAD P (ported iPad) drop out
        # of sold AND activated; PEND P (new-number iPhone) stays sold.
        office, reps = C.activation_rates(self.lines, TODAY)
        self.assertEqual(office["0-30"]["sold"], 4)
        self.assertEqual(office["0-30"]["activated"], 3)
        self.assertEqual(office["31-60"]["sold"], 0)
        self.assertIsNone(office["31-60"]["rate"])
        self.assertEqual(reps["Nick Smedra"]["0-30"]["rate"], 1.0)
        self.assertEqual(reps["Andrew Park"]["0-30"]["rate"], 0.5)
        self.assertEqual(C.excluded_orders(self.lines, TODAY),
                         {"upgrade": 1, "device": 2})

    def test_product_box(self):
        # activated in window: HENRY W SPE1 (iPhone, non-BYOD), SPE2 (BYOD,
        # disconnected), MARIA G (Air); pending: PEND P (new iPhone);
        # UPG U / TAB T / PAD P are not orders; OLD O posted 9/5 is outside.
        box = C.product_box(self.lines, TODAY)
        self.assertEqual(box["wireless"], {"act": 1, "disc": 0, "pend": 1})
        self.assertEqual(box["byod"], {"act": 1, "disc": 1, "pend": 0})
        self.assertEqual(box["air"], {"act": 1, "disc": 0, "pend": 0})
        self.assertEqual(box["internet"], {"act": 0, "disc": 0, "pend": 0})
        self.assertEqual(box["all_orders"], {"act": 3, "disc": 1, "pend": 1})
        # the box ties out with the churn summary's wireless base
        s = C.churn_summary(self.lines, TODAY)
        self.assertEqual(box["wireless"]["act"] + box["byod"]["act"], s["base"]["Wireless"])

    def test_rolloff_formula_template_defaults(self):
        from automations.vantura_churn import fill as VF
        cols = {"rem": "X", "key": "AD"}
        self.assertEqual(
            VF.U_FORMULA_T.format(r=2, wl="$B$5", air="$B$6", inet="$B$7", **cols),
            VF.U_FORMULA.format(r=2, **cols))

    def test_is_byod_on_pending_lines(self):
        # plan set: it decides. plan 'Pending' / blank: the device decides.
        self.assertTrue(C.is_byod({"wireless_ip": "BYOD", "device": "iPhone 18 Pro - 256GB - Black"}))
        self.assertFalse(C.is_byod({"wireless_ip": "Next36 w/o Next Up", "device": "XT2215-1"}))
        self.assertTrue(C.is_byod({"wireless_ip": "Pending", "device": "XT2215-1"}))
        self.assertTrue(C.is_byod({"wireless_ip": "", "device": "SM-G991U BYO"}))
        self.assertTrue(C.is_byod({"wireless_ip": "Pending", "device": "iPhone 8 Plus (A1864)"}))
        self.assertFalse(C.is_byod({"wireless_ip": "Pending", "device": "Galaxy A17 5G - 128GB - Black"}))
        self.assertFalse(C.is_byod({"wireless_ip": "", "device": ""}))

    def test_counts_as_order(self):
        by = {l["customer"]: l for l in self.lines}
        self.assertTrue(C.counts_as_order(by["HENRY W"]))     # ported phone
        self.assertTrue(C.counts_as_order(by["PEND P"]))      # new-number phone
        self.assertTrue(C.counts_as_order(by["MARIA G"]))     # Air
        self.assertFalse(C.counts_as_order(by["UPG U"]))      # upgrade
        self.assertFalse(C.counts_as_order(by["TAB T"]))      # tablet, 'new'
        self.assertFalse(C.counts_as_order(by["PAD P"]))      # ported iPad

    def test_tiers_and_status(self):
        self.assertEqual(comp.tier_for(2.2, comp.NONBYOD_0_30), 4)
        self.assertEqual(comp.tier_for(2.21, comp.NONBYOD_0_30), 3)
        self.assertEqual(comp.tier_for(7.51, comp.NONBYOD_0_30), 1)
        self.assertEqual(comp.tier_for(5.5, comp.BYOD_0_30), 4)
        self.assertIsNone(comp.tier_for(None, comp.BYOD_0_30))
        self.assertEqual(comp.payout("3-3", False), (213, 193))
        self.assertEqual(comp.payout("3-3", True), (188, 168))
        self.assertEqual(comp.payout("4-4", False), (233, 213))
        ts = C.tier_status(C.churn_summary(self.lines, TODAY), TODAY)
        self.assertEqual(ts["products"]["byod"]["tier"], 1)       # 1/1 = 100%
        self.assertEqual(ts["products"]["non_byod"]["tier"], 4)   # 0/1
        line = C.status_line(ts)
        self.assertIn("Tier 3-3 ($213 OOF / $193 INFP", line)
        self.assertIn("BYOD 1/1 = 100.0% (Tier 1 band)", line)
        self.assertIn("≤19 port activations", line)
        self.assertIn("not counted: 1 ported tablet/wearable, 1 tablet/wearable line, 1 upgrade)", line)

    def test_rep_dnq(self):
        self.assertIsNone(comp.rep_dnq(8.0, 10, 50.0, 10))   # under the floors
        self.assertTrue(comp.rep_dnq(7.1, 20, None, 0))
        self.assertTrue(comp.rep_dnq(None, 0, 59.9, 20))
        self.assertIsNone(comp.rep_dnq(7.0, 25, 60.0, 25))


if __name__ == "__main__":
    unittest.main()
