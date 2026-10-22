"""Valeria's 1st rounds read off Ana's Slack replies, not the sheet (10/22).

    python -m unittest automations.ad_photo_threads.test_slack_rows
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.ad_photo_threads import collect, config

DAY = dt.date(2026, 10, 21)


class SlackRowTest(unittest.TestCase):
    def test_name_ad_verdict_stars(self):
        r = collect.slack_row(
            "Devin Hyatt – AT&amp;T Team Member – YES – 1:15 – :star::star::star::star:☆ (4/5)\n"
            "Customer service experience.", DAY)
        self.assertEqual(r[config.COL_NAME], "Devin Hyatt")
        self.assertEqual(r[config.COL_TITLE], "AT&T Team Member")
        self.assertEqual(r[config.COL_QUALIFY], "Qualify")
        self.assertEqual(r[config.COL_STARS], "4")
        self.assertEqual(r[config.COL_DATE], "10/21/2026")

    def test_old_format_has_no_ad(self):
        r = collect.slack_row("*Leeann Rolon – NO – 1:15 PM –* :star:*️*:star:*️*\n*Summary:* ...", DAY)
        self.assertEqual(r[config.COL_NAME], "Leeann Rolon")
        self.assertEqual(r[config.COL_TITLE], "")
        self.assertEqual(r[config.COL_QUALIFY], "Disqualify")
        self.assertEqual(r[config.COL_STARS], "2")

    def test_verdict_left_out(self):
        r = collect.slack_row("Ivonne Zarate – Entry Level Sales Account Assistant – 4:15 – :star::star::star:", DAY)
        self.assertEqual(r[config.COL_TITLE], "Entry Level Sales Account Assistant")
        self.assertEqual(r[config.COL_QUALIFY], "")

    def test_time_line_before_the_name(self):
        r = collect.slack_row("3:00\n*Sheyla Garcia – YES – 3:00 PM –* :star:", DAY)
        self.assertEqual(r[config.COL_NAME], "Sheyla Garcia")

    def test_chatter_is_no_row(self):
        self.assertIsNone(collect.slack_row("Thank you!", DAY))
        self.assertIsNone(collect.slack_row("running 5 min late - sorry", DAY))


if __name__ == "__main__":
    unittest.main()
