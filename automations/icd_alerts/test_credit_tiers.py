"""The three credit-check alerts (Carlos 2026-10-22, option A).

    python -m unittest automations.icd_alerts.test_credit_tiers

Pinned with the 10/21 Wireless grid the probe read (2026-10-23): Jacari
Melbert had 3 on the tablet, 2 credit checks and 1 passed.
"""
import unittest
from unittest import mock

from automations.icd_alerts import config as C
from automations.icd_alerts import post as P
from automations.icd_alerts import relay as R
from automations.shared import credit_check_line as L
from automations.shared import saraplus as S

# The frozen header table's labels, in SaraPlus's order (first 9 of 27).
HEADERS = ["", "", "", "Records", "Credit Checked", "Credit Passed",
           "Credit AR Triggered", "Credit AR Not Cleared", "Sales"]


def row(kind, name, *nums):
    return ["", kind, name] + [str(n) for n in nums]


class ParseCreditTests(unittest.TestCase):
    def test_reads_by_label(self):
        rows = [row("3_Location", "SOUTH SHORE", 9, 5, 4, 2, 1, 3),
                row("5_Agent", "JACARI MELBERT", 3, 2, 1, 2, 1, 0),
                row("5_Agent", "ANA GRIFFIN", 3, 2, 2, 0, 0, 0),
                row("5_Agent", "BILL HIRWA", 1, 0, 0, 0, 0, 0)]
        got = S.parse_credit(HEADERS, rows)
        self.assertEqual(got, {
            "JACARI MELBERT": {"Credit Checked": 2, "Credit Passed": 1},
            "ANA GRIFFIN": {"Credit Checked": 2, "Credit Passed": 2}})

    def test_any_agent_depth_counts(self):
        # The row-type number is the depth; an office one level deeper
        # still marks its reps "..._Agent".
        got = S.parse_credit(HEADERS, [row("7_Agent", "LIAN REYES", 1, 1, 1, 0, 0, 0)])
        self.assertIn("LIAN REYES", got)

    def test_missing_labels_is_unknown_not_zero(self):
        self.assertIsNone(S.parse_credit(["", "", "", "Records"], []))


class WireTests(unittest.TestCase):
    REC = {"office_key": "colten", "campaign": None}
    SALES = {"JACARI MELBERT": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 2}}
    CREDIT = {"JACARI MELBERT": {"Credit Checked": 2, "Credit Passed": 1},
              "ANA GRIFFIN": {"Credit Checked": 2, "Credit Passed": 2}}

    def test_rides_inside_the_sales_for_an_opted_in_office(self):
        out = R._with_credit(self.SALES, self.CREDIT, self.REC)
        self.assertEqual(out["JACARI MELBERT"]["Credit Passed"], 1)
        self.assertEqual(out["JACARI MELBERT"]["NL"], 2)
        # a rep with checks and no sale still travels, with zero sales
        self.assertEqual(out["ANA GRIFFIN"]["Int"], 0)
        self.assertEqual(out["ANA GRIFFIN"]["Credit Checked"], 2)

    def test_untouched_for_everyone_else(self):
        rec = {"office_key": "rashad", "campaign": None}
        self.assertEqual(R._with_credit(self.SALES, self.CREDIT, rec), self.SALES)

    def test_not_read_adds_nothing(self):
        self.assertEqual(R._with_credit(self.SALES, None, self.REC), self.SALES)

    def test_the_sale_metrics_ignore_the_extra_keys(self):
        # decide_sales picks the campaign's metrics by name, so a credit
        # check never reads as a sale.
        sales = R._with_credit({}, self.CREDIT, self.REC)
        sold, _, _ = P.decide_sales(sales, {}, None)
        self.assertEqual(sold, [])


class DecideCreditTests(unittest.TestCase):
    def s(self, **reps):
        return {k.replace("_", " "): {"Int": 0, "Credit Checked": c, "Credit Passed": p}
                for k, (c, p) in reps.items()}

    def test_first_relay_of_the_day_is_a_baseline(self):
        lines, state, base = P.decide_credit(self.s(JACARI_MELBERT=(2, 1)), None)
        self.assertTrue(base)
        self.assertEqual(lines, [])
        self.assertEqual(state["JACARI MELBERT"]["Credit Checked"], 2)

    def test_agent_update_mid_day_does_not_dump_the_morning(self):
        # last posted has sales but no credit keys yet: several reps at once
        # is the backlog arriving, not live activity.
        last = {"JACARI MELBERT": {"Int": 0}}
        now = self.s(JACARI_MELBERT=(2, 1), ANA_GRIFFIN=(2, 2))
        lines, _, base = P.decide_credit(now, last)
        self.assertTrue(base)
        self.assertEqual(lines, [])

    def test_one_rep_first_check_announces(self):
        lines, _, base = P.decide_credit(self.s(LIAN_REYES=(1, 0)), {})
        self.assertFalse(base)
        self.assertEqual(lines, [L.credit_line("LIAN REYES", 1, 1)])

    def test_check_then_pass(self):
        last = self.s(JACARI_MELBERT=(1, 0))
        lines, state, _ = P.decide_credit(self.s(JACARI_MELBERT=(2, 1)), last)
        self.assertEqual(lines, [L.credit_line("JACARI MELBERT", 2, 1),
                                 L.passed_line("JACARI MELBERT", 1, 1)])
        self.assertEqual(state["JACARI MELBERT"], {"Credit Checked": 2, "Credit Passed": 1})

    def test_a_failed_check_never_posts_a_pass(self):
        last = self.s(AUNDRE_BROWDER=(0, 0))
        lines, _, _ = P.decide_credit(self.s(AUNDRE_BROWDER=(1, 0)), last)
        self.assertEqual(lines, [L.credit_line("AUNDRE BROWDER", 1, 1)])

    def test_only_up(self):
        last = self.s(ANA_GRIFFIN=(2, 2))
        lines, state, _ = P.decide_credit(self.s(ANA_GRIFFIN=(1, 1)), last)
        self.assertEqual(lines, [])
        self.assertEqual(state["ANA GRIFFIN"]["Credit Checked"], 2)

    def test_state_written_back_beside_the_sales(self):
        out = P.with_credit_state({"ANA GRIFFIN": {"Int": 1}},
                                  {"ANA GRIFFIN": {"Credit Checked": 2, "Credit Passed": 2}})
        self.assertEqual(out["ANA GRIFFIN"], {"Int": 1, "Credit Checked": 2, "Credit Passed": 2})
        # and the next read of it sees the checks as already posted
        lines, _, _ = P.decide_credit(out, out)
        self.assertEqual(lines, [])


class WordingTests(unittest.TestCase):
    def test_the_three_lines(self):
        self.assertEqual(L.tablet_line("JACARI MELBERT", 9, 1),
                         ":mag: Jacari Melbert got someone on the tablet (9 today).")
        self.assertEqual(L.tablet_line("JACARI MELBERT", 9, 2),
                         ":mag: Jacari Melbert got 2 people on the tablet (9 today).")
        self.assertEqual(L.credit_line("JACARI MELBERT", 2, 1),
                         ":credit_card: Jacari Melbert got a credit check (2 today).")
        self.assertEqual(L.passed_line("JACARI MELBERT", 1, 1),
                         ":white_check_mark: Jacari Melbert got a passed credit check (1 today).")

    def test_tablet_wording_only_through_decide_when_asked(self):
        lines, _, _ = P.decide({"JACARI MELBERT": 9}, {"JACARI MELBERT": 8},
                               line=L.tablet_line)
        self.assertIn("on the tablet", lines[0])
        lines, _, _ = P.decide({"JACARI MELBERT": 9}, {"JACARI MELBERT": 8})
        self.assertIn("credit check", lines[0])


class OptInListTests(unittest.TestCase):
    def test_the_yes_offices(self):
        for k in ("carlos-b2batt", "colten", "kash", "maxamad", "Jamis", "aya"):
            self.assertTrue(C.credit_tiers_wanted(k), k)
        for k in ("rashad", "isaiah", ""):
            self.assertFalse(C.credit_tiers_wanted(k), k)

    def test_the_laptop_pass_follows_its_enrollments(self):
        with mock.patch.object(C, "active_enrollments",
                               return_value=[{"office_key": "isaiah"}]):
            self.assertFalse(C.credit_tiers_here())
        with mock.patch.object(C, "active_enrollments",
                               return_value=[{"office_key": "jamis10"},
                                             {"office_key": "jamis"}]):
            self.assertTrue(C.credit_tiers_here())


if __name__ == "__main__":
    unittest.main()
