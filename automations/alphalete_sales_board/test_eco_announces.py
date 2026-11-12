"""Raf's ECO computer announces his office in Slack; this sweep does not.

From 2026-11-03 both did, so every credit check and sale in #alphalete-sales
landed twice. Megan, 2026-11-12: "we need raf's running on his ECO machine."

    python -m unittest automations.alphalete_sales_board.test_eco_announces

Reads source only. Nothing here opens SaraPlus, a sheet, Slack or Messages.
"""
import re
import unittest
from pathlib import Path

from automations.alphalete_sales_board import config as C

RUN = (Path(__file__).resolve().parent / "run.py").read_text()


class TheSweepLeavesSlackToEco(unittest.TestCase):

    def test_the_switch_is_off(self):
        self.assertIs(C.SLACK_LINES, False)

    def test_every_slack_line_sits_behind_the_switch(self):
        i = RUN.index("if not baseline and C.SLACK_LINES:")
        j = RUN.index("CARLOS'S FOURTEEN", i)
        gated = RUN[i:j]
        # Both kinds: the per-sale hype and the credit-check lines.
        self.assertIn("N.slack(_line", gated)
        self.assertIn("N.slack(N.records_line(", gated)
        # ...and none of them anywhere else in the sweep.
        outside = RUN[:i] + RUN[j:]
        self.assertEqual(re.findall(r"\bN\.slack\(", outside), [])

    def test_the_texts_are_not_behind_it(self):
        # The leaderboard text to his chats is the sweep's own job and stays.
        i = RUN.index("for group in C.LIVE_GROUPS:")
        self.assertLess(i, RUN.index("if not baseline and C.SLACK_LINES:"))
        self.assertIn("N.text_group(group, body", RUN[i:i + 200])

    def test_a_skipped_line_is_said_in_the_log(self):
        self.assertIn("Slack lines left to Raf's ECO computer", RUN)


if __name__ == "__main__":
    unittest.main()
