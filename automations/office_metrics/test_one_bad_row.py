"""One office's bad row must not stop every office (2026-10-21: Joseph's
re-added email made validate() refuse all 24 offices' metrics).

    python -m unittest automations.office_metrics.test_one_bad_row
"""
from __future__ import annotations

import unittest

from automations.office_metrics.runner import _problems_for

JOSEPH = ("joseph: has BOTH a Slack channel (logan-legacy-sales) and email_to "
          "(joseph@loganlegacygroup.com) — pick one.")
SHARED = ("cody: channel C1 (aeon-sales) already used by 'rashad' — two offices "
          "sharing a channel BOTH refuse")


class OneBadRow(unittest.TestCase):

    def test_other_offices_run(self):
        self.assertEqual(_problems_for("cody", [JOSEPH]), [])
        self.assertEqual(_problems_for("rashad", [JOSEPH]), [])

    def test_the_bad_office_still_refuses(self):
        self.assertEqual(_problems_for("joseph", [JOSEPH]), [JOSEPH])

    def test_shared_channel_blocks_both_offices(self):
        self.assertEqual(_problems_for("cody", [SHARED]), [SHARED])
        self.assertEqual(_problems_for("rashad", [SHARED]), [SHARED])
        self.assertEqual(_problems_for("kash", [SHARED]), [])


if __name__ == "__main__":
    unittest.main()
