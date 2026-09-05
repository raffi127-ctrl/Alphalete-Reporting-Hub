"""Apex routing — who lands in which payroll box. Offline, no sheet, no browser.

Payroll is the least forgiving place to guess, so the safe direction is pinned:
an unrecognised house team is EXCLUDED, never quietly entered.

    python -m unittest automations.commission_sheet.test_apex
"""
import datetime as dt
import unittest
from unittest import mock

from automations.commission_sheet import apex


def _sheet(rows):
    """rows = [(team, first, last, paid)] starting at FIRST_REP_ROW."""
    people = [["Y", t, "", "", f, l] for t, f, l, _p in rows]
    paid = [[p] for _t, _f, _l, p in rows]
    header = [""] * 108 + ["WE 8/30", "", ""]

    ws = mock.Mock()
    def get(rng, **kw):
        if rng.startswith("A1:GZ1"):
            return [header]
        if rng.startswith("A3:F"):
            return people
        return paid
    ws.get.side_effect = get
    sh = mock.Mock(); sh.worksheet.return_value = ws
    return sh


def _plan(rows):
    with mock.patch("automations.recruiting_report.fill.open_by_key",
                    return_value=_sheet(rows)):
        return apex.plan(dt.date(2026, 8, 30))


class Routing(unittest.TestCase):
    def test_ordinary_rep_is_a_commission_adjustment(self):
        p = _plan([("Ceaseless", "Ana", "Griffin", "$800.00")])
        self.assertEqual([e.name for e in p.entries], ["Ana Griffin"])

    def test_partner_pay_goes_to_bonuses(self):
        p = _plan([("A - Partner Pay", "Willie", "Partner Pay", "$224.03")])
        self.assertEqual([e.name for e in p.bonuses], ["Willie Partner Pay"])

    def test_jds_own_line_is_never_entered(self):
        # "I'm not on there. I just put mine on there just for keeping track
        # of PL purposes." Entering it would pay someone not on Apex payroll.
        p = _plan([("A - Sales Manager", "JD", "Mascorro", "$1,500.00")])
        self.assertEqual([e.name for e in p.excluded], ["JD Mascorro"])
        self.assertEqual(p.entries, [])
        self.assertEqual(p.bonuses, [])

    def test_unconfirmed_house_team_is_excluded_not_guessed(self):
        # Chef and Food Cost are house costs, not people.
        p = _plan([("A - Chef", "", "Chef", "$400.00"),
                   ("A - Food Cost", "", "Food", "$1,000.00"),
                   ("A - Sales Manager", "Basil", "Elhassan", "$1,138.60")])
        self.assertEqual(len(p.excluded), 3)
        self.assertEqual(p.entries, [])
        self.assertEqual(p.bonuses, [])

    def test_excluded_money_is_not_in_the_total(self):
        p = _plan([("Ceaseless", "Ana", "Griffin", "$800.00"),
                   ("A - Chef", "", "Chef", "$400.00")])
        self.assertEqual(p.total, 800.0)

    def test_no_payout_is_skipped_not_entered_as_zero(self):
        p = _plan([("Ceaseless", "Ana", "Griffin", ""),
                   ("Ceaseless", "Bob", "Smith", "$0.00")])
        self.assertEqual(len(p.skipped), 2)
        self.assertEqual(p.entries, [])

    def test_a_missing_week_banner_is_an_error_not_a_wrong_column(self):
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=_sheet([("T", "A", "B", "$1")])):
            with self.assertRaises(KeyError):
                apex.plan(dt.date(2026, 9, 6))


class ApplyIsNotWired(unittest.TestCase):
    def test_apply_refuses_rather_than_pretending(self):
        with self.assertRaises(NotImplementedError):
            apex.apply(apex.Plan(week=dt.date(2026, 8, 30),
                                 banner="WE 8/30", paid_col="DF"))


if __name__ == "__main__":
    unittest.main()
