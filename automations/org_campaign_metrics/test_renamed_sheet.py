"""A renamed 'Low Metrics Owner' sheet is picked up, a guess is not (2026-10-31).

    python -m unittest automations.org_campaign_metrics.test_renamed_sheet
"""
import unittest

from automations.org_campaign_metrics.pull_nds import renamed_sheet


def _err(names):
    return ("Couldn't find the 'Low Metrics Owner' sheet in the Crosstab "
            "dialog — saw %d thumb(s): %r. The view may have changed."
            % (len(names), names))


class RenamedSheet(unittest.TestCase):
    def test_sibling_that_still_says_owner(self):
        self.assertEqual(renamed_sheet("Low Metrics Owner", _err(
            ["Low Metrics Flags", "Low Metrics Owners", "Low Metrics ICD"])),
            "Low Metrics Owners")

    def test_the_only_other_low_metrics_sheet(self):
        self.assertEqual(renamed_sheet("Low Metrics Owner", _err(
            ["Low Metrics Flags", "Low Metrics (ICD)", "Map"])),
            "Low Metrics (ICD)")

    def test_flags_is_never_a_stand_in(self):
        self.assertIsNone(renamed_sheet("Low Metrics Owner", _err(
            ["Low Metrics Flags", "Map"])))

    def test_two_candidates_is_a_guess(self):
        self.assertIsNone(renamed_sheet("Low Metrics Owner", _err(
            ["Low Metrics Flags", "Low Metrics A", "Low Metrics B"])))

    def test_other_sheets_untouched(self):
        self.assertIsNone(renamed_sheet("Rep Summary", _err(
            ["Low Metrics Owners"])))


if __name__ == "__main__":
    unittest.main()
