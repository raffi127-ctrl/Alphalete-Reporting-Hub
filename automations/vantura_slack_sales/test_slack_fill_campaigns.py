"""The NDS board ("B2B" key) is SaraPlus-owned since 2026-11-03: the Slack
fill never writes it; Verizon still fills from Slack."""
import unittest

from automations.vantura_slack_sales import run as R


class SlackFillCampaigns(unittest.TestCase):
    def test_nds_dropped_verizon_kept(self):
        said = []
        self.assertEqual(R.slack_fill_campaigns(["B2B", "Verizon"], said.append), ["Verizon"])
        self.assertTrue(said and "SaraPlus" in said[0])

    def test_nothing_owned_nothing_said(self):
        said = []
        self.assertEqual(R.slack_fill_campaigns(["Verizon"], said.append), ["Verizon"])
        self.assertEqual(said, [])


if __name__ == "__main__":
    unittest.main()
