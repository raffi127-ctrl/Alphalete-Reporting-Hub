"""The fixers are steps on the card of the report they fix, not cards
(Eve 2026-10-19). A typo in a phase id is invisible: the fix still runs, the
step just never colours.

    PYTHONPATH=. .venv/bin/python -m unittest automations.focus_report_fixer.test_hub_phase
"""
import unittest
from unittest import mock

from automations.focus_report_fixer import run as FR
from automations.sales_board_fixer import run as SB


def _card(cid):
    from automations.hub_cards import AUTOMATED_REPORTS
    return next(c for c in AUTOMATED_REPORTS if c["id"] == cid)


class FixersAreSteps(unittest.TestCase):
    def test_focus_fixer_is_the_last_step_of_every_focus_card(self):
        for cid in ("recruiting", "recruiting-carlos", "recruiting-alphalete-org",
                    "nds-program-focus"):
            self.assertEqual(_card(cid)["phases"][-1], FR.HUB_PHASE, cid)

    def test_salesboard_fixers_are_steps_of_the_sales_board_card(self):
        ph = _card("alphalete-sales-board")["phases"]
        self.assertIn(SB.HUB_PHASE, ph)
        self.assertIn(SB.HUB_PHASE_OWNERS, ph)

    def test_no_card_of_their_own(self):
        from automations.day_orchestrator import hub_coverage as hc
        for rid in ("focus_report_fixer", "sales_board_fixer", "sales_board_fixer_owners"):
            self.assertTrue(hc.is_internal(rid), rid)

    def test_the_row_never_registers_a_card(self):
        with mock.patch("automations.shared.hub_activity.log_completed") as log:
            FR.hub_phase(FR.HUB_PHASE, "x", True)
        self.assertIs(log.call_args.kwargs["register_card"], False)
        self.assertEqual(log.call_args.kwargs["status"], "success")

    def test_only_the_full_monday_pass_colours_the_step(self):
        with mock.patch.object(FR, "_main", return_value=0), \
                mock.patch.object(FR, "hub_phase") as hp:
            FR.main(["--tab", "Marcellus Butler", "--apply"])
            FR.main([])
            hp.assert_not_called()
            FR.main(["--all-tabs", "--apply"])
            hp.assert_called_once_with(FR.HUB_PHASE, "Lucy Focus Report Fixer", True)

    def test_a_crash_paints_the_step_red(self):
        with mock.patch.object(FR, "_main", side_effect=RuntimeError("boom")), \
                mock.patch.object(FR, "hub_phase") as hp:
            with self.assertRaises(RuntimeError):
                FR.main(["--all-tabs", "--apply"])
            hp.assert_called_once_with(FR.HUB_PHASE, "Lucy Focus Report Fixer", False)


if __name__ == "__main__":
    unittest.main()
