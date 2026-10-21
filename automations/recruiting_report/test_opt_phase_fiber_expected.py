"""Expected Fiber Sales math in opt_phase (2026-10-20).

The Focus Report's 'Expected Fiber Sales (120 days, 17wks)' and '... Weekly'
rows are the 2% penetration goal: Total Leads x 2%, and that / 17. The bulk
Fiber crosstab pull was writing its 'Fiber Sales (Fixed)' column (ACTUAL
sales) into Expected instead, so every tab's Weekly came out low. Loom from
the field, 2026-10-20: 143,250 x 2% / 17 = 168.5 -> 169; 62,696 -> 74.

Run:  python -m automations.recruiting_report.test_opt_phase_fiber_expected

3.9-safe — the mini runs Python 3.9.
"""
from __future__ import annotations

import unittest

# Same heavy-dep stubs as the crosstab tests (gspread / patchright).
from automations.recruiting_report import test_opt_phase_crosstab  # noqa: F401
from automations.recruiting_report import opt_phase  # noqa: E402


class ExpectedIsLeadsTimesGoal(unittest.TestCase):
    def test_loom_example_one(self):
        self.assertEqual(opt_phase._fiber_expected(143250), 2865)
        self.assertEqual(opt_phase._fiber_weekly(143250), 169)

    def test_loom_example_two(self):
        self.assertEqual(opt_phase._fiber_weekly("62,696"), 74)

    def test_half_rounds_up_not_to_even(self):
        # 168.5 must be 169 — Python's round() would give 168.
        self.assertEqual(opt_phase._round_half_up(168.5), 169)
        self.assertEqual(opt_phase._round_half_up(2.5), 3)

    def test_zero_and_blank(self):
        self.assertEqual(opt_phase._fiber_weekly(0), 0)
        self.assertIsNone(opt_phase._fiber_weekly(""))


if __name__ == "__main__":
    unittest.main()
