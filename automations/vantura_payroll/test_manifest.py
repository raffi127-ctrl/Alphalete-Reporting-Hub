"""Vantura payroll: a live run proves delivery only when the week is ready.

2026-10-08: the 10/7 ticket stayed open after a clean re-run — "nothing can
confirm it DELIVERED" — because the run wrote no manifest.

    python -m unittest automations.vantura_payroll.test_manifest
"""
import unittest

from automations.shared import delivery_check
from automations.vantura_payroll import run as R

OK_SUMMARY = "refresh: ok"
OK_CHECKS = ("orphan B2B payouts (paid, $0 brought): $0.00 | tie-out: "
             "Commission==P&L ✓ (spare roster rows: 9)")


class Holes(unittest.TestCase):
    def test_ready_week_has_no_holes(self):
        self.assertEqual(R.payroll_holes(OK_SUMMARY, OK_CHECKS, "", ""), [])

    def test_findings_for_carlos_are_not_holes(self):
        checks = ("orphan B2B payouts (paid, $0 brought): $120.00  ⚠ "
                  "INVESTIGATE | ⚠ only 2 spare roster row(s) left")
        self.assertEqual(R.payroll_holes(OK_SUMMARY, checks, "", ""), [])

    def test_each_undone_step_is_named(self):
        holes = R.payroll_holes(
            "refresh: SKIPPED (web app not configured)",
            "tie-out FAILED ⚠: Commission brought … | tie-out check errored (x)",
            "ORG DD sweep FAILED (boom) — check those reps by hand",
            "ValueError('x')")
        self.assertEqual(len(holes), 5)

    def test_manifest_id_is_found_from_the_config_key(self):
        self.assertIn(R.REPORT_ID,
                      delivery_check.manifest_ids("vantura_payroll"))


if __name__ == "__main__":
    unittest.main()
