"""NDS lines without upgrades, tablets or wearables (Carlos 2026-10-22).

    python -m unittest automations.icd_alerts.test_nds_lines

Carlos's two examples: Jacob at 11 lines = 7 ported + 4 upgrades (7 count),
and a line count of 6 = 5 phones + 1 tablet (5 count).
"""
import unittest
from unittest import mock

from automations.icd_alerts import config as C
from automations.icd_alerts import post as P
from automations.icd_alerts import relay as R
from automations.shared import saraplus as S

# The frozen header table's labels (the 10/21 probe), leading cells blank.
HEADERS = ["", "", "", "Records", "Credit Checked", "Credit Passed", "Sales",
           "Line Count", "New Lines", "Port Lines", "Upgrade Lines", "BYOD Lines",
           "Phones", "Tablets", "Wearables"]


def row(name, line_count, new, port, upg, byod, phones, tablets, wear):
    return ["", "5_Agent", name, "1", "1", "1", "1", str(line_count), str(new),
            str(port), str(upg), str(byod), str(phones), str(tablets), str(wear)]


NDS = {"office_key": "jacob", "campaign": "nds"}


class ParseLinesTests(unittest.TestCase):
    def test_reads_by_label(self):
        got = S.parse_lines(HEADERS, [row("JACOB SMITH", 11, 0, 7, 4, 0, 11, 0, 0),
                                      row("ANA GRIFFIN", 0, 0, 0, 0, 0, 0, 0, 0)])
        self.assertEqual(got, {"JACOB SMITH": {"New Lines": 0, "Port Lines": 7,
                                               "Upgrade Lines": 4, "Tablets": 0,
                                               "Wearables": 0}})

    def test_missing_labels_is_unknown(self):
        self.assertIsNone(S.parse_lines(["", "", "", "Records", "Line Count"], []))

    def test_credit_still_reads_the_same_grid(self):
        got = S.parse_credit(HEADERS, [row("JACOB SMITH", 11, 0, 7, 4, 0, 11, 0, 0)])
        self.assertEqual(got["JACOB SMITH"], {"Credit Checked": 1, "Credit Passed": 1})


class NdsLinesTests(unittest.TestCase):
    def lines(self, *rows):
        return S.parse_lines(HEADERS, list(rows))

    def test_upgrades_leave_nl_for_the_upgrades_section(self):
        sales = {"JACOB SMITH": {"Int": 0, "Int Up": 1, "DTV": 0, "NL": 11, "Air": 1}}
        out = R._nds_lines(sales, self.lines(row("JACOB SMITH", 11, 0, 7, 4, 0, 11, 0, 0)), NDS)
        self.assertEqual(out["JACOB SMITH"]["NL"], 7)
        self.assertEqual(out["JACOB SMITH"]["Int Up"], 5)   # 1 Air + 4 upgrade lines
        board = P._nds_scoreboard(out, [], None)
        self.assertIn("NL's: 7", board)
        self.assertIn("Upgrades: 4", board)
        self.assertIn("TOTALS: 8", board)                   # 1 Air + 7 NL

    def test_tablets_and_wearables_do_not_count(self):
        sales = {"ANA GRIFFIN": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 6, "Air": 0}}
        out = R._nds_lines(sales, self.lines(row("ANA GRIFFIN", 6, 6, 0, 0, 0, 5, 1, 0)), NDS)
        self.assertEqual(out["ANA GRIFFIN"]["NL"], 5)
        # Justin Carlos Avila on 10/21: 1 new + 1 port, 1 phone + 1 watch
        out = R._nds_lines({}, self.lines(row("JUSTIN AVILA", 2, 1, 1, 0, 0, 1, 0, 1)), NDS)
        self.assertEqual(out["JUSTIN AVILA"]["NL"], 1)

    def test_byod_is_not_taken_off(self):
        # Thomas Crenshaw on 10/21: 9 ported, 5 of them BYOD, 9 phones
        out = R._nds_lines({}, self.lines(row("THOMAS CRENSHAW", 9, 0, 9, 0, 5, 9, 0, 0)), NDS)
        self.assertEqual(out["THOMAS CRENSHAW"]["NL"], 9)

    def test_rep_missing_from_the_grid_sold_no_lines(self):
        sales = {"BILL HIRWA": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 2, "Air": 1}}
        out = R._nds_lines(sales, {}, NDS)
        self.assertEqual(out["BILL HIRWA"]["NL"], 0)
        self.assertEqual(out["BILL HIRWA"]["Air"], 1)

    def test_not_read_is_untouched(self):
        sales = {"JACOB SMITH": {"NL": 11}}
        self.assertEqual(R._nds_lines(sales, None, NDS), sales)
        att = {"office_key": "kash", "campaign": "att"}
        self.assertEqual(R._nds_lines(sales, None, att), sales)

    def test_every_att_office_counts_new_and_port_only(self):
        """Megan 2026-10-26: no watches or tablets. Raf 2026-10-27: a
        wireless upgrade is not a sale, an internet upgrade is -- so the
        upgrade LINES are dropped and Int Up (internet) is left alone."""
        att = {"office_key": "kash", "campaign": "att"}
        sales = {"JACOB SMITH": {"Int": 1, "Int Up": 1, "DTV": 0, "NL": 9},
                 "ANA GRIFFIN": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 2}}
        # 9 lines: 5 new + 2 port + 2 upgrade; 1 tablet + 1 watch among them
        lines = self.lines(row("JACOB SMITH", 9, 5, 2, 2, 0, 7, 1, 1))
        out = R._nds_lines(sales, lines, att)
        self.assertEqual(out["JACOB SMITH"]["NL"], 5)
        self.assertEqual(out["JACOB SMITH"]["Int Up"], 1)
        self.assertEqual(out["JACOB SMITH"]["Int"], 1)
        self.assertEqual(out["ANA GRIFFIN"]["NL"], 0)      # no wireless lines
        self.assertEqual(out["ANA GRIFFIN"]["Int"], 1)
        self.assertEqual(sales["JACOB SMITH"]["NL"], 9)    # input not mutated

    def test_b2b_upgrade_lines_are_not_a_sale(self):
        b2b = {"office_key": "carlos-b2batt", "campaign": "b2b_att"}
        sales = {"RODOLFO BAZAN": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 2, "Air": 0}}
        out = R._nds_lines(sales, self.lines(row("RODOLFO BAZAN", 2, 0, 1, 1, 0, 2, 0, 0)), b2b)
        self.assertEqual((out["RODOLFO BAZAN"]["NL"], out["RODOLFO BAZAN"]["Int Up"]), (1, 0))

    def test_raf_sweep_counts_new_and_port_only(self):
        agents = [{"name": "JACOB SMITH", "wireless_lines_sold": 9},
                  {"name": "ANA GRIFFIN", "wireless_lines_sold": 2}]
        S.lines_sold(agents, self.lines(row("JACOB SMITH", 9, 5, 2, 2, 0, 7, 1, 1)))
        self.assertEqual([a["wireless_lines_sold"] for a in agents], [5, 0])
        self.assertEqual(S.lines_sold([{"name": "X", "wireless_lines_sold": 4}], None)[0]
                         ["wireless_lines_sold"], 4)

    def test_payload_carries_it(self):
        lines = self.lines(row("JACOB SMITH", 11, 0, 7, 4, 0, 11, 0, 0))
        rec = dict(NDS, relay_key="k")
        with mock.patch.object(R, "machine_id", return_value="m"), \
             mock.patch.object(R, "machine_label", return_value="m"), \
             mock.patch.object(R, "is_desktop", return_value=True), \
             mock.patch.object(R, "_never_sleeps", return_value=True):
            try:
                body = R.payload({}, __import__("datetime").date(2026, 10, 21), rec,
                                 sales={"JACOB SMITH": {"NL": 11}}, lines=lines)
            except Exception as e:  # other machine probes in payload
                self.skipTest("payload needs this machine: %s" % e)
        self.assertEqual(body["sales"]["JACOB SMITH"]["NL"], 7)


B2B = {"office_key": "carlos-b2batt", "campaign": "b2b_att"}


class B2bAttLinesTests(unittest.TestCase):
    """Sebastian Avellaneda 2026-10-23, the A Players text vs Carlos's
    SaraPlus Wireless grid for the same day."""

    def lines(self, *rows):
        return S.parse_lines(HEADERS, list(rows))

    def day(self):
        # What the AT&T grid relayed: Jorge's Air sat in Int Up, and NL was
        # the whole Line Count.
        sales = {
            "JORGE JOSE HERNANDEZ MOLINA": {"Int": 0, "Int Up": 1, "DTV": 0, "NL": 5, "Air": 1},
            "DIEGO JAVIER DEL POZO BORRES": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 4, "Air": 0},
            "ANDREW DE LA TORRE": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 2, "Air": 0},
            "RODOLFO BAZAN": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 2, "Air": 0},
        }
        lines = self.lines(
            row("JORGE JOSE HERNANDEZ MOLINA", 5, 0, 5, 0, 5, 5, 0, 0),
            row("DIEGO JAVIER DEL POZO BORRES", 4, 0, 4, 0, 3, 4, 0, 0),
            row("ANDREW DE LA TORRE", 2, 0, 2, 0, 1, 2, 0, 0),
            row("RODOLFO BAZAN", 2, 0, 1, 1, 1, 2, 0, 0))
        return R._nds_lines(sales, lines, B2B)

    def test_upgrade_line_is_not_a_sale(self):
        # Raf 2026-10-27: a wireless upgrade is not a sale. It was moved into
        # Int Up here until then, which made it one.
        self.assertEqual(self.day()["RODOLFO BAZAN"]["NL"], 1)
        self.assertEqual(self.day()["RODOLFO BAZAN"]["Int Up"], 0)

    def test_air_is_internet_not_an_upgrade(self):
        jorge = self.day()["JORGE JOSE HERNANDEZ MOLINA"]
        self.assertEqual((jorge["Int"], jorge["Int Up"], jorge["NL"]), (1, 0, 5))

    def test_the_text(self):
        board = P.scoreboard_text(self.day(), [], "b2b_att")
        self.assertIn("Jorge Jose Hernandez Molina 6 (1 Int, 5 NL)", board)
        self.assertIn("Rodolfo Bazan 1 (1 NL)", board)
        for word in ("INT: 1", "Upgrades: 0", "NL's: 12", "TOTALS: 13"):
            self.assertIn(word, board)

    def test_air_moves_even_when_the_wireless_pass_failed(self):
        sales = {"JORGE": {"Int": 0, "Int Up": 1, "DTV": 0, "NL": 5, "Air": 1}}
        self.assertEqual(R._nds_lines(sales, None, B2B)["JORGE"]["Int"], 1)

    def test_the_office_key_alone_is_enough(self):
        rec = {"office_key": "carlos-b2batt", "campaign": "att"}
        out = R._nds_lines({}, self.lines(row("RODOLFO BAZAN", 2, 0, 1, 1, 1, 2, 0, 0)), rec)
        self.assertEqual(out["RODOLFO BAZAN"]["NL"], 1)

    def test_wireless_pass_runs_for_b2b_att(self):
        with mock.patch.object(C, "active_enrollments", return_value=[B2B]):
            self.assertTrue(C.wireless_lines_here())
        with mock.patch.object(C, "active_enrollments",
                               return_value=[{"office_key": "kash", "campaign": "att"}]):
            self.assertFalse(C.wireless_lines_here())


class NdsHereTests(unittest.TestCase):
    def test_follows_the_enrollments(self):
        with mock.patch.object(C, "active_enrollments",
                               return_value=[{"office_key": "kash", "campaign": "att"}]):
            self.assertFalse(C.nds_here())
        with mock.patch.object(C, "active_enrollments",
                               return_value=[{"office_key": "jacob", "campaign": "NDS"}]):
            self.assertTrue(C.nds_here())


if __name__ == "__main__":
    unittest.main()


class SweepHandsTheCountsToSendTests(unittest.TestCase):
    """2026-10-23: `lines` was reused for the alert strings, so every NDS
    office's send crashed on a list from 11:38 on -- silently, no fault."""

    def test_a_later_sweep_sends_the_line_counts_not_the_alert_text(self):
        from automations.icd_alerts import run as RUN
        counts = {"JACOB SMITH": {"New Lines": 0, "Port Lines": 7,
                                  "Upgrade Lines": 4, "Tablets": 0, "Wearables": 0}}
        read = {"records": {"JACOB SMITH": 2}, "sales": {}, "credit": None,
                "lines": counts, "empty_evidence": None}
        sent = {}
        from automations.icd_alerts import selfupdate
        with mock.patch.object(selfupdate, "run", return_value=False), \
             mock.patch.object(RUN.C, "active_enrollments", return_value=[NDS]), \
             mock.patch.object(RUN.sara_read, "sara_held_until", return_value=None), \
             mock.patch.object(RUN.W, "timed", return_value=read), \
             mock.patch.object(RUN.St, "load", return_value={}), \
             mock.patch.object(RUN.St, "is_baseline", return_value=False), \
             mock.patch.object(RUN.St, "deltas", return_value={"JACOB SMITH": 1}), \
             mock.patch.object(RUN.St, "save"), \
             mock.patch.object(RUN.R, "send",
                               side_effect=lambda *a, **k: sent.update(k)):
            self.assertEqual(RUN.cmd_once(True, False, C.today()), 0)
        self.assertEqual(sent["lines"], counts)


class ACrashIsReportedTests(unittest.TestCase):
    """The 10/23 send crash filed nothing; the offices looked switched off."""

    def test_an_uncaught_crash_files_a_fault_then_still_fails(self):
        from automations.icd_alerts import run as RUN
        filed = []
        with mock.patch.object(RUN, "_main", side_effect=TypeError("boom")), \
             mock.patch.object(RUN, "_report",
                               side_effect=lambda s, e, **k: filed.append(s)), \
             mock.patch.object(RUN, "_log"):
            with self.assertRaises(TypeError):
                RUN.main(["--once"])
        self.assertEqual(filed, ["crash"])

    def test_a_timeout_is_not_filed_twice(self):
        from automations.icd_alerts import run as RUN
        filed = []
        with mock.patch.object(RUN, "_main", side_effect=RUN.W.SweepTimeout("x")), \
             mock.patch.object(RUN, "_report",
                               side_effect=lambda s, e, **k: filed.append(s)):
            with self.assertRaises(RUN.W.SweepTimeout):
                RUN.main(["--once"])
        self.assertEqual(filed, [])
