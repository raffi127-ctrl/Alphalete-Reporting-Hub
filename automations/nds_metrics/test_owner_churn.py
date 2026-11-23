"""owner_churn: wireless churn ICD totals per owner in Tableau's buckets, Airs
and BYODs in (Carlos 2026-11-23: "do the same table for wireless churn.
Include airs and BYODs. Just the table that shows ICD totals 0-30 day 31 day
60 day 90 day Churn What tableau churn reports look at")."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_metrics import owner_churn as OC

TODAY = dt.date(2026, 11, 23)
HDR = ["Owner & Office", "Rep", "Customer Name", "sp.Order Date (copy)",
       "Product Type (Broken Out)", "DTR Status", "spe.dtr Posted Date", "spe.Name",
       "spe.TN Type", "Device Description", "Wireless Installment Plan", "Measure Names"]
KHALIL = "KHALIL MANSOUR\r [alphalete management group, inc. dba hab]"


def ln(spe, posted_days_ago, status="Posted", prod="WIRELESS", tn="port",
       device="iPhone 17 - 256GB - Black", plan="Next36", owner=KHALIL):
    posted = TODAY - dt.timedelta(days=posted_days_ago)
    od = posted - dt.timedelta(days=3)
    row = [owner, "Rep A", "Cust " + spe, od.strftime("%m/%d/%Y"), prod, status,
           posted.strftime("%m/%d/%Y"), spe, tn, device, plan]
    return [row + [m] for m in ("Sales (All) (1)", "Unit Count")]


def export():
    rows = [HDR]
    rows += ln("S1", 5)                                    # 0-30 phone, active
    rows += ln("S2", 10, status="Disconnected")            # 0-30 phone, churned
    rows += ln("S3", 12, device="XT2215-1", plan="BYOD")   # 0-30 BYOD
    rows += ln("S4", 20, prod="AIR", tn="", device="", plan="")    # 0-30 Air
    rows += ln("S5", 15, prod="NEW INTERNET", tn="", device="", plan="")  # fiber: out
    rows += ln("S6", 8, tn="upgrade")                      # upgrade: out
    rows += ln("S7", 9, device="iPad Air 11 - 128GB - Blue")       # tablet: out
    rows += ln("S8", 45, status="Disconnected", device="SM-S921U BYO", plan="BYOD")  # 30 Day
    rows += ln("S9", 75)                                   # 60 Day
    rows += ln("S10", 100, status="Disconnected", prod="AIR", tn="", device="", plan="")  # 90 Day
    rows += ln("S11", 130)                                 # past 120: out
    rows += ln("S12", 5, status="Shipped")                 # not activated: out
    return rows


class Counting(unittest.TestCase):
    def setUp(self):
        from automations.nds_metrics import owner_weeks as OW
        cols, data, i_owner = OW.load_export(export(), log=lambda m: None)
        rows, _hit = OW.office_rows(cols, data, i_owner, "Khalil Mansour")
        self.total, self.per_cls = OC.office_churn(cols.header, rows, TODAY)

    def test_buckets_and_what_counts(self):
        t = self.total
        self.assertEqual((t["0-30 Day"]["disc"], t["0-30 Day"]["act"]), (1, 4))  # S1 S2 S3 S4
        self.assertEqual((t["30 Day"]["disc"], t["30 Day"]["act"]), (1, 1))      # S8
        self.assertEqual((t["60 Day"]["disc"], t["60 Day"]["act"]), (0, 1))      # S9
        self.assertEqual((t["90 Day"]["disc"], t["90 Day"]["act"]), (1, 1))      # S10 (Air)

    def test_airs_and_byods_are_in(self):
        self.assertEqual(self.per_cls["byod"]["0-30 Day"]["act"], 1)
        self.assertEqual(self.per_cls["air"]["0-30 Day"]["act"], 1)
        self.assertEqual(self.per_cls["wireless"]["0-30 Day"]["act"], 2)


class Picture(unittest.TestCase):
    def test_one_row_per_owner_tableau_bucket_columns(self):
        o1 = OC.OfficeChurn("Carlos Hidalgo", "NDS",
                            {"0-30 Day": {"act": 50, "disc": 2}, "30 Day": {"act": 0, "disc": 0}}, {}, 9)
        o2 = OC.OfficeChurn("Rafael Hidalgo", "D2D", {"0-30 Day": {"act": 40, "disc": 4}}, {}, 9)
        got = {}
        with mock.patch("automations.b2b_metrics.rep_boards.render_table_png",
                        lambda title, sub, columns, rows, out: got.update(
                            title=title, sub=sub, columns=columns, rows=rows) or out):
            OC.summary_png([o1, o2], TODAY, out_dir=mock.MagicMock())
        self.assertEqual(got["columns"], ["0-30 Day", "30 Day", "60 Day", "90 Day"])
        self.assertEqual([r[0] for r in got["rows"]], ["Carlos Hidalgo", "Rafael Hidalgo"])
        c = got["rows"][0][3]["0-30 Day"]
        self.assertEqual((c["disc"], c["act"], c["rate"], c["color"]), ("2", "50", "4.0%", "Yellow"))
        self.assertEqual(got["rows"][0][3]["30 Day"], {})      # nothing activated: blank
        self.assertIn("Rafael: his office's D2D wireless churn view", got["sub"])


class Coverage(unittest.TestCase):
    """The 150-day D2D crosstab times out; a shorter pull blanks the buckets it
    cannot reach instead of undercounting them."""

    def test_short_window_blanks_the_old_buckets(self):
        total = {b: {"act": 10, "disc": 1} for b, _lo, _hi in OC.BUCKETS}
        got = OC.cells(total, covered=105)
        self.assertEqual(got["0-30 Day"]["rate"], "10.0%")
        self.assertEqual(got["60 Day"]["rate"], "10.0%")         # 90 + 15 <= 105
        self.assertEqual(got["90 Day"], {"rate": "n/a", "color": ""})
        got = OC.cells(total, covered=60)
        self.assertEqual(got["30 Day"], {"rate": "n/a", "color": ""})
        self.assertEqual(OC.cells(total)["90 Day"]["rate"], "10.0%")   # 150 days: all

    def test_chunks_walk_back_contiguously(self):
        self.assertEqual(OC.D2D_CHUNKS[0][1], 61)                # right after the 60-day pull
        self.assertEqual(OC.D2D_CHUNKS[1][1], OC.D2D_CHUNKS[0][0] + 1)
        self.assertEqual(OC.D2D_CHUNKS[-1][0], OC.LOOKBACK_DAYS)

    def test_merge_lines_up_columns_by_name(self):
        import tempfile
        from pathlib import Path
        a = [["Owner Name", "Rep", "DTR Status"], ["Rafael Hidalgo", "A", "Posted"]]
        b = [["Rep", "Owner Name", "DTR Status"], ["B", "Rafael Hidalgo", "Disconnected"]]
        with tempfile.TemporaryDirectory() as td:
            pa, pb = Path(td, "a.csv"), Path(td, "b.csv")
            pa.write_text("x")
            pb.write_text("x")
            with mock.patch("automations.commission_sheet.sources.read_crosstab",
                            side_effect=lambda p: a if Path(p).name == "a.csv" else b):
                cols, data, i_owner = OC.load_merged([pa, pb], log=lambda m: None)
        self.assertEqual(cols.header, ["Owner Name", "Rep", "DTR Status"])
        self.assertEqual(data, [["Rafael Hidalgo", "A", "Posted"],
                                ["Rafael Hidalgo", "B", "Disconnected"]])


class TableauPhones(unittest.TestCase):
    """Carlos: "What tableau churn reports look at" -- phones are the view's
    ICD totals, Air comes on top from the order log."""

    def test_view_phones_plus_order_log_air(self):
        o = OC.OfficeChurn("Jairo Ruiz", "NDS",
                           {b: {"act": 999, "disc": 999} for b, _lo, _hi in OC.BUCKETS},
                           {"air": {"0-30 Day": {"act": 48, "disc": 5},
                                    "90 Day": {"act": 31, "disc": 9}}}, 9)
        phones = {"Jairo Ruiz": OC._from_view({"0-30": {"num": 69.0, "denom": 1382.0},
                                               "30": {"num": 83.0, "denom": 1503.0},
                                               "60": {"num": 151.0, "denom": 1483.0},
                                               "90": {"num": 199.0, "denom": 1265.0}})}
        OC.apply_tableau([o], phones, log=lambda m: None)
        self.assertEqual(o.basis, "tableau")
        self.assertEqual(o.total["0-30 Day"], {"act": 1430, "disc": 74})
        self.assertEqual(o.total["30 Day"], {"act": 1503, "disc": 83})
        self.assertEqual(o.total["90 Day"], {"act": 1296, "disc": 208})

    def test_no_view_keeps_the_order_log_count_and_says_so(self):
        o = OC.OfficeChurn("Someone Else", "D2D", {"0-30 Day": {"act": 10, "disc": 1}}, {}, 9)
        OC.apply_tableau([o], {}, log=lambda m: None)
        self.assertEqual(o.basis, "order log")
        self.assertEqual(o.total["0-30 Day"], {"act": 10, "disc": 1})
        got = {}
        with mock.patch("automations.b2b_metrics.rep_boards.render_table_png",
                        lambda title, sub, columns, rows, out: got.update(sub=sub) or out):
            OC.summary_png([o], TODAY, out_dir=mock.MagicMock())
        self.assertIn("Someone: counted off the order log", got["sub"])


class Entry(unittest.TestCase):
    def test_names_and_dm(self):
        with mock.patch.object(OC, "run", return_value=0) as run:
            OC.entry(["--owner-churn", "Carlos Hidalgo;Khalil", "Mansour", "--dm", "U1"])
        self.assertEqual(run.call_args[0][0], ["Carlos Hidalgo", "Khalil Mansour"])
        self.assertEqual(run.call_args[1]["dm"], "U1")

    def test_dm_only_to_the_id_given_and_from_the_metrics_token_without_a_bot(self):
        o = OC.OfficeChurn("Carlos Hidalgo", "NDS", {"0-30 Day": {"act": 5, "disc": 1}}, {}, 9)
        sent = []
        with mock.patch.object(OC, "read_offices", return_value=([o], [])), \
             mock.patch.object(OC, "tableau_phones", return_value={}), \
             mock.patch.object(OC, "summary_png", return_value=mock.MagicMock(name="p")), \
             mock.patch("automations.shared.slack_metrics_post.BOT_TOKEN_PATH") as tok, \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("automations.shared.slack_metrics_post.dm_user_with_file",
                        side_effect=lambda *a, **k: sent.append(k)):
            import os
            os.environ.pop("SLACK_BOT_TOKEN", None)
            tok.exists.return_value = False
            OC.run(["Carlos Hidalgo"], dm="U046G04P5LG", log=lambda m: None, today=TODAY)
        self.assertEqual([k["user"] for k in sent], ["U046G04P5LG"])
        self.assertFalse(sent[0]["as_bot"])


if __name__ == "__main__":
    unittest.main()
