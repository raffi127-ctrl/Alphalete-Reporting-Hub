"""owner_weeks: the crew's week-ending activation board for another owner's
whole office (Carlos 2026-11-23: "Make me an activation rate by week ending
for Khalil Colten Jairo and Rafael and send to me only on slack")."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_metrics import activation_by_week as AW
from automations.nds_metrics import owner_weeks as OW
from automations.nds_metrics.run import Cols

TODAY = dt.date(2026, 11, 23)          # a Monday
HDR = ["Owner & Office", "Rep", "sp.Order Date (copy)", "DTR Status",
       "Product Type (Broken Out)", "sp.SPM Number", "spe.Name", "Measure Names",
       "Measure Values"]
KHALIL = "KHALIL MANSOUR\r [alphalete management group, inc. dba hab]"
JAIRO = "JAIRO RUIZ\r [profits management, inc.]"
OTHER = "DAIGHN DUNN\r [veritas management, inc.]"


def line(owner, rep, od, st, prod="WIRELESS", spm="SPM1", spe="SPE-1"):
    return [[owner, rep, od, st, prod, spm, spe, m, "1"]
            for m in ("Sales (All) (1)", "Unit Count")]


def export():
    rows = [["junk title"], HDR]
    rows += line(KHALIL, "Amet Shemo", "11/17/2026", "Posted", spm="A", spe="SPE-1")
    rows += line(KHALIL, "Amet Shemo", "11/17/2026", "Shipped", spm="A", spe="SPE-2")
    rows += line(KHALIL, "Yazn Allahham", "11/10/2026", "Canceled", spm="B", spe="SPE-3")
    rows += line(KHALIL, "Yazn Allahham", "11/10/2026", "Disconnected", spm="B", spe="SPE-4")
    rows += line(KHALIL, "Old Rep", "10/01/2026", "Posted", spm="C", spe="SPE-5")
    rows += line(KHALIL, "Amet Shemo", "11/18/2026", "Posted", prod="AIR", spm="D", spe="SPE-6")
    rows += line(JAIRO, "Some Rep", "11/18/2026", "Posted", spm="E", spe="SPE-7")
    rows += line(OTHER, "Abdul Rafay Sheikh", "11/18/2026", "Posted", spm="F", spe="SPE-8")
    return rows


class Matching(unittest.TestCase):
    LABELS = [KHALIL, JAIRO, OTHER, "CARLOS HIDALGO TX\r [alphalete specialized marketing inc(tx]"]

    def test_full_and_first_names(self):
        self.assertEqual(OW.match_owner("Jairo Ruiz", self.LABELS), [JAIRO])
        self.assertEqual(OW.match_owner("khalil", self.LABELS), [KHALIL])
        self.assertEqual(OW.match_owner("Carlos Hidalgo", self.LABELS), [self.LABELS[3]])

    def test_owner_name_only_not_the_business_or_a_rep(self):
        # 'alphalete' is in Khalil's business name, 'Rafay' a rep -- neither is an owner
        self.assertEqual(OW.match_owner("Alphalete", self.LABELS), [])
        self.assertEqual(OW.match_owner("Rafael Hidalgo", self.LABELS), [])
        self.assertEqual(OW.owner_name(KHALIL), "KHALIL MANSOUR")


class Counting(unittest.TestCase):
    def setUp(self):
        self.cols, self.data, self.i_owner = OW.load_export(export(), log=lambda m: None)

    def test_measure_rows_collapse_to_one_per_line(self):
        self.assertEqual(len(self.data), 8)

    def test_whole_office_wireless_by_week(self):
        rows, hit = OW.office_rows(self.cols, self.data, self.i_owner, "Khalil Mansour")
        self.assertEqual(hit, [KHALIL])
        weeks, data = AW.aggregate_tableau(self.cols, rows, TODAY,
                                           since=TODAY - dt.timedelta(days=60))
        self.assertEqual(weeks, [dt.date(2026, 10, 4), dt.date(2026, 11, 15),
                                 dt.date(2026, 11, 22)])
        wk = data[AW.TOTAL][dt.date(2026, 11, 22)]
        self.assertEqual((wk["lines"], wk["activated"], wk["pending"]), (2, 1, 1))   # AIR left out
        wk = data[AW.TOTAL][dt.date(2026, 11, 15)]
        self.assertEqual((wk["activated"], wk["cancelled"], wk["churned"]), (1, 1, 1))
        self.assertNotIn("Some Rep", data)                      # Jairo's rep stays on Jairo's

    def test_crews_nds_floor_is_still_the_default(self):
        rows, _ = OW.office_rows(self.cols, self.data, self.i_owner, "Khalil")
        weeks, _ = AW.aggregate_tableau(self.cols, rows, TODAY)
        self.assertNotIn(dt.date(2026, 10, 4), weeks)           # before NDS_SINCE 10/19

    def test_fiber_log_counts_every_product(self):
        rows, _ = OW.office_rows(self.cols, self.data, self.i_owner, "Khalil")
        _w, data = AW.aggregate_tableau(self.cols, rows, TODAY, wireless_only=False)
        self.assertEqual(data[AW.TOTAL][dt.date(2026, 11, 22)]["lines"], 3)    # + the AIR line


class Board(unittest.TestCase):
    def _rows(self, **kw):
        cols, data, i_owner = OW.load_export(export(), log=lambda m: None)
        rows, _ = OW.office_rows(cols, data, i_owner, "Khalil")
        weeks, agg = AW.aggregate_tableau(cols, rows, TODAY,
                                          since=TODAY - dt.timedelta(days=60))
        weeks = weeks[-2:]                                      # 'Old Rep' sold before these
        got = {}
        with mock.patch("automations.b2b_metrics.rep_boards.render_table_png",
                        lambda title, sub, columns, rows, out: got.update(
                            title=title, rows=rows, columns=columns) or out):
            AW.render(weeks, agg, mock.Mock(), today=TODAY, **kw)
        return got

    def test_office_total_label_and_quiet_reps_dropped(self):
        got = self._rows(total_label="Office Total", active_reps_only=True)
        labels = [r[0] for r in got["rows"]]
        self.assertTrue(labels[0].startswith("Office Total (all reps)"), labels)
        self.assertNotIn("Old Rep", labels)
        self.assertIn("Amet Shemo", labels)

    def test_crew_board_unchanged_by_default(self):
        got = self._rows()
        labels = [r[0] for r in got["rows"]]
        self.assertTrue(labels[0].startswith("Crew Total (all reps)"), labels)
        self.assertIn("Old Rep", labels)                        # the crew board keeps every rep row

    def test_summary_is_one_row_per_owner(self):
        o1 = OW.Office("Khalil", "Khalil Mansour", "NDS",
                       [dt.date(2026, 11, 15), dt.date(2026, 11, 22)],
                       {AW.TOTAL: {dt.date(2026, 11, 22): {"lines": 4, "activated": 3}}})
        o2 = OW.Office("Rafael", "Rafael Hidalgo", "Fiber", [dt.date(2026, 11, 22)],
                       {AW.TOTAL: {dt.date(2026, 11, 22): {"lines": 2, "activated": 1}}})
        got = {}
        with mock.patch("automations.b2b_metrics.rep_boards.render_table_png",
                        lambda title, sub, columns, rows, out: got.update(
                            rows=rows, columns=columns) or out):
            OW.summary_png([o1, o2], TODAY, out_dir=mock.MagicMock())
        self.assertEqual(got["columns"], ["WE 11/15", "WE 11/22"])
        self.assertEqual([r[0] for r in got["rows"]], ["Khalil Mansour", "Rafael Hidalgo (fiber)"])
        self.assertEqual(got["rows"][0][3]["WE 11/22"]["rate"], "75.0%")


class Entry(unittest.TestCase):
    def test_quoted_and_unquoted_names(self):
        for args in (["--owner-weeks", "Khalil Mansour;Colten Wright", "--dm", "U1"],
                     ["--owner-weeks", "Khalil", "Mansour;Colten", "Wright", "--dm", "U1"]):
            with mock.patch.object(OW, "run", return_value=0) as run:
                OW.entry(args)
            self.assertEqual(run.call_args[0][0], ["Khalil Mansour", "Colten Wright"])
            self.assertEqual(run.call_args[1]["dm"], "U1")

    def test_no_dm_means_nothing_sent(self):
        with mock.patch.object(OW, "run", return_value=0) as run:
            OW.entry(["--owner-weeks", "Jairo Ruiz"])
        self.assertIsNone(run.call_args[1]["dm"])


if __name__ == "__main__":
    unittest.main()
