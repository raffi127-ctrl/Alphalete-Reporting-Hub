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
        self.assertIn("Rafael's off the D2D order log", got["sub"])


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
