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


class MultiSlackRowTest(unittest.TestCase):
    """Salik's threads (10/23 on): several candidates per reply."""

    def rows(self, text):
        return [(r[config.COL_NAME], r[config.COL_TITLE], r[config.COL_QUALIFY],
                 r[config.COL_STARS]) for r in collect.multi_slack_rows(text, DAY)]

    def test_double_slash_job_then_ad(self):
        self.assertEqual(self.rows(
            "1:20\nShanell Robinson//Property office//Entry Level AT&amp;T Team Member"
            "//Start ASAP//2:<star://Schedule:yes>\n\n"
            "Janay Stanback//Floor Supervisor United Airline//AT&amp;T Retail Sales Associate"
            "//:star:3//Start ASAP//Schedule:yes\nZekaryah-tech issue reschedule requested"),
            [("Shanell Robinson", "Entry Level AT&T Team Member", "Qualify", "2"),
             ("Janay Stanback", "AT&T Retail Sales Associate", "Qualify", "3")])

    def test_double_slash_ad_after_start(self):
        self.assertEqual(self.rows(
            "Tanisha Mason//McDonalds//Start ASAP//:star:2//Entry Level Sales Representative AT&amp;T//Schedule:yes"),
            [("Tanisha Mason", "Entry Level Sales Representative AT&T", "Qualify", "2")])

    def test_double_slash_no_ad_is_blank(self):
        self.assertEqual(self.rows(
            "Quante Malone//Package Handler Fed-ex//:star:3//start within a week//Schedule Yes"),
            [("Quante Malone", "", "Qualify", "3")])

    def test_job_glued_to_name(self):
        self.assertEqual(self.rows(
            ":white_check_mark:Natacha Nze- Accounting//AT&T Retail Sales Associate//:star::star:\n"
            ":white_check_mark:Aamaron Lewis-Esthetician//Entry Level AT&T Team Member//:star::star:"),
            [("Natacha Nze", "AT&T Retail Sales Associate", "Qualify", "2"),
             ("Aamaron Lewis", "Entry Level AT&T Team Member", "Qualify", "2")])

    def test_pipes(self):
        self.assertEqual(self.rows(
            "*9.45*\n• Alyssa Bartsch - canvassing for the election - can start ASAP- :x: not a good fit"
            "  ||  Entry Level AT&T Team Member\n"
            "• Chiyu Keyser (CC)- bilingual - can start two weeks - Qualified :white_check_mark: 4:star:"
            " || _Event Sales &amp; Marketing Assistant_"),
            [("Alyssa Bartsch", "Entry Level AT&T Team Member", "Disqualify", ""),
             ("Chiyu Keyser", "Event Sales & Marketing Assistant", "Qualify", "4")])

    def test_valeria_line_is_not_multi(self):
        self.assertEqual(self.rows("Devin Hyatt – AT&amp;T Team Member – YES – 1:15 – :star:"), [])
        self.assertEqual(self.rows("no one showed up"), [])

    def test_salik_thread_names(self):
        rx = config.office("salik")["sources"][0]["thread_re"]
        for t in ("*FIRST ROUND INTERVIEW THREAD 11/16*", "*FIRST ROUND THREAD 11.13*",
                  "*FIRST ROUND THREAD: 10/23*"):
            self.assertTrue(rx.search(t), t)



class LabeledRowsTest(unittest.TestCase):
    """Aya + Haytham, in-house since November (Camila 11/24)."""

    def test_aya_job_ad(self):
        rows = collect.labeled_slack_rows(
            "12:30\nAna lopez :white_check_mark:/marketing/mor4e handson/3 weeks/3 star/"
            "job ad New application for AT&amp;T Representative, Carmel, IN,\n"
            "Bea ruiz:x:/different schedule/JOB AD NO AD\n"
            "Cara Diaz:white_check_mark:/plasma center/2 weeks/3 stars", DAY)
        self.assertEqual([r[config.COL_NAME] for r in rows],
                         ["Ana lopez", "Bea ruiz", "Cara Diaz"])
        self.assertEqual(rows[0][config.COL_TITLE], "AT&T Representative, Carmel, IN")
        self.assertEqual(rows[0][config.COL_STARS], "3")
        self.assertEqual(rows[0][config.COL_QUALIFY], "Qualify")
        self.assertEqual(rows[1][config.COL_TITLE], "")
        self.assertEqual(rows[1][config.COL_QUALIFY], "Disqualify")
        self.assertEqual(rows[2][config.COL_TITLE], "")

    def test_haytham_job_title(self):
        rows = collect.labeled_slack_rows(
            "2:20 pm\n\n"
            "• Dana Smith-  :x:Commute too far! *Job Title:* Customer Sales Associate (Spanish Required)\n"
            "• Eli Jones - Owns Moving company, ASAP, Job Title: Event Marketing &amp; Sales "
            "Assistant:white_check_mark: (5:star:)", DAY)
        self.assertEqual([r[config.COL_NAME] for r in rows], ["Dana Smith", "Eli Jones"])
        self.assertEqual(rows[0][config.COL_TITLE], "Customer Sales Associate (Spanish Required)")
        self.assertEqual(rows[0][config.COL_QUALIFY], "Disqualify")
        self.assertEqual(rows[1][config.COL_TITLE], "Event Marketing & Sales Assistant")
        self.assertEqual(rows[1][config.COL_STARS], "5")

    def test_haytham_line_without_job_title_is_blank(self):
        rows = collect.labeled_slack_rows("1:20 pm\n\n• Fay Brown- :x: was busy doing something else", DAY)
        self.assertEqual([(r[config.COL_NAME], r[config.COL_TITLE]) for r in rows], [("Fay Brown", "")])

    def test_chat_is_not_a_row(self):
        self.assertEqual(collect.labeled_slack_rows("<@U0BG6LK4JJH> for tmr", DAY), [])


if __name__ == "__main__":
    unittest.main()
