"""The PNL's DD check: the arithmetic, without a browser."""
import datetime as dt
import unittest

from automations.icd_alerts import pnl as P

CSV = (
    "﻿cl.ICD Owner Name,cl.DD Week,REP.Name,Total $ to ICD\n"
    "Jairo Ruiz,10/18/2026,Jane Doe (12345),\"$1,000.50\"\n"
    "Jairo Ruiz,10/18/2026,Jane Doe (12345),200\n"
    "Jairo Ruiz,10/18/2026,,($50.00)\n"
    "Jairo Ruiz,10/11/2026,Jane Doe (12345),300\n"
    "Carlos Hidalgo,10/18/2026,Someone Else (9),999\n"
)


class DdByRep(unittest.TestCase):
    def test_sums_per_rep_per_week_for_the_owner_only(self):
        weeks, seen = P.dd_by_rep(CSV, "Jairo Ruiz")
        we = dt.date(2026, 10, 18)
        self.assertEqual(weeks[we], {"Jane Doe": 1200.5, P.NO_REP: -50.0})
        self.assertEqual(weeks[dt.date(2026, 10, 11)], {"Jane Doe": 300.0})
        self.assertEqual(seen["owners"], 2)

    def test_owner_login_file_without_owner_column_is_all_theirs(self):
        text = "cl.DD Week,REP.Name,Total $ to ICD\n10/18/2026,A B (1),10\n"
        weeks, seen = P.dd_by_rep(text, "Jairo Ruiz")
        self.assertEqual(weeks, {dt.date(2026, 10, 18): {"A B": 10.0}})
        self.assertIn("owner", seen["missing"])

    def test_line_says_what_was_missing(self):
        weeks, seen = P.dd_by_rep("Foo,Bar\n1,2\n", "Jairo Ruiz")
        self.assertTrue(P.check_line(weeks, seen).startswith("DD file has no"))

    def test_line_gives_newest_week_total(self):
        weeks, seen = P.dd_by_rep(CSV, "Jairo Ruiz")
        self.assertIn("WE 2026-10-18: 2 reps $1,150.50", P.check_line(weeks, seen))

    def test_only_offices_that_asked(self):
        self.assertTrue(P.wanted({"office_key": "jairo15"}))
        self.assertFalse(P.wanted({"office_key": "kash"}))

    def test_check_due_office_hours_and_once(self):
        noon = dt.datetime(2026, 10, 29, 12)
        self.assertTrue(P.check_due({}, noon))
        self.assertFalse(P.check_due({}, dt.datetime(2026, 10, 29, 3)))
        self.assertFalse(P.check_due({"dd_ok_v4": "2026-10-29"}, noon))


    def test_check_takes_the_first_sheet_with_data(self):
        import unittest.mock as m
        found = [("DDDETAIL", "ERROR 404"), ("DDDETAILORG", "ICD.Full Name\nX\n"),
                 ("ICDddDetail", CSV)]
        with m.patch.object(P, "fetch_dd_csvs", return_value=found), \
                m.patch("automations.icd_alerts.ov_read._context") as ctx, \
                m.patch("patchright.sync_api.sync_playwright"):
            ctx.return_value.pages = [object()]
            ok, line, _ = P.check({"owner": "Jairo Ruiz"})
        self.assertTrue(ok)
        self.assertTrue(line.startswith("ICDddDetail DD OK"))

    def test_owner_cut_line_by_line_with_icd_rep_name(self):
        text = ("cl.DD Week,cl.ICD Owner Name,cl.ICD Rep Name,Total $ to ICD\n"
                "10/18/2026,Jairo Ruiz,A B (1),10\n10/18/2026,Jairo Ruiz,A B (1),5\n")
        weeks, seen = P.dd_by_rep(text, "Jairo Ruiz")
        self.assertEqual(weeks, {dt.date(2026, 10, 18): {"A B": 15.0}})

    def test_long_format_keeps_only_the_icd_total_measure(self):
        text = ("cl.DD Week,cl.ICD Owner Name,cl.ICD Rep Name,Measure Names,Measure Values\n"
                "10/18/2026,Jairo Ruiz,A B (1),Total $ to ICD,\"1,000\"\n"
                "10/18/2026,Jairo Ruiz,A B (1),Units,3\n"
                "10/18/2026,Jairo Ruiz,,Total $ to ICD,50\n")
        weeks, seen = P.dd_by_rep(text, "Jairo Ruiz")
        self.assertEqual(weeks, {dt.date(2026, 10, 18): {"A B": 1000.0, P.NO_REP: 50.0}})
        self.assertEqual(seen["measures"], ["Total $ to ICD", "Units"])
        self.assertIn("money from 'Total $ to ICD'", P.check_line(weeks, seen))

    def test_long_format_without_a_money_measure_lists_them(self):
        text = ("cl.DD Week,cl.ICD Rep Name,Measure Names,Measure Values\n"
                "10/18/2026,A B,Units,3\n")
        weeks, seen = P.dd_by_rep(text, "x")
        self.assertEqual(P.check_line(weeks, seen),
                         "DD file has no money measure (measures: Units)")

    def test_money_column_found_by_hint(self):
        text = "cl.DD Week,cl.ICD Rep Name,cl.Some $ To ICD Paid\n10/18/2026,A B,7\n"
        weeks, seen = P.dd_by_rep(text, "x")
        self.assertEqual(seen["total_col"], "cl.Some $ To ICD Paid")


APEX = ("Pay Period,10/19/2026 - 10/25/2026\n"
        "Owner\nFirst Name,Last Name,Gross Pay\nJAIRO,RUIZ,5000\nTotal,5000\n"
        "Sales Reps\nFirst Name,Last Name,Gross Pay\n"
        "DANNY,PEREZ,400\nYAMELY,FERNANDEZ,300\nNEW,GUY,50\nTotal,750\n"
        "Company Total,5750\n")


class ApexTests(unittest.TestCase):
    def test_reps_only_never_the_owner(self):
        per, pay = P.apex_pay(APEX)
        self.assertEqual(per, (dt.date(2026, 10, 19), dt.date(2026, 10, 25)))
        self.assertEqual(pay, {"Danny Perez": 400.0, "Yamely Fernandez": 300.0,
                               "New Guy": 50.0})

    def test_match_by_full_then_first_last(self):
        hit, miss, extra = P.match_reps(
            {"Danny Alexander Perez": 1, "Yamely Fernandez": 2, "Gone Rep": 3,
             P.NO_REP: 4}, ["Danny Perez", "Yamely Fernandez", "New Guy"])
        self.assertEqual(hit, ["Danny Alexander Perez", "Yamely Fernandez"])
        self.assertEqual(miss, ["Gone Rep"])
        self.assertEqual(extra, ["New Guy"])

    def test_line_carries_no_money(self):
        per, pay = P.apex_pay(APEX)
        weeks = {dt.date(2026, 10, 25): {"Danny Perez": 900.0, "Gone Rep": 10}}
        line = P.apex_line(per, pay, weeks)
        self.assertEqual(line, "Apex OK: period 10/19-10/25, 3 people paid; "
                         "DD WE 2026-10-25 reps found in Apex 1/2; "
                         "DD not in Apex: Gone Rep; "
                         "Apex not in DD: New Guy, Yamely Fernandez")
        self.assertNotIn("$", line)
        self.assertNotIn("400", line)

    def test_apex_waits_for_the_dd_then_hourly(self):
        import time
        noon = dt.datetime(2026, 10, 29, 12)
        self.assertFalse(P.apex_due({}, noon))
        self.assertTrue(P.apex_due({"dd_ok_v4": "x"}, noon))
        self.assertFalse(P.apex_due({"dd_ok_v4": "x", "apex_ok_v1": "y"}, noon))
        self.assertFalse(P.apex_due({"dd_ok_v4": "x",
                                     "apex_tried_v1": time.time()}, noon))
        self.assertFalse(P.apex_due({"dd_ok_v4": "x"},
                                    dt.datetime(2026, 10, 29, 22)))

    def test_apex_window_is_offered(self):
        from automations.icd_alerts import autoprompt as AU
        self.assertEqual(AU.SYSTEMS["apex"]["module"],
                         "automations.icd_alerts.apex_signin")


if __name__ == "__main__":
    unittest.main()
