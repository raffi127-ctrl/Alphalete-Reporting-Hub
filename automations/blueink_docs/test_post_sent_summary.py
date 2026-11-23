"""--post-sent-summary: tell the room about packets that ALREADY went out.

2026-11-23: the daily agent had never fired, the 11 owed were sent by hand from
the queue without --slack, and the recruiting room never heard. This posts the
summary off the Blue Ink Log and sends nothing. Slack is faked here.

    python -m unittest automations.blueink_docs.test_post_sent_summary
"""
import datetime as dt
import unittest
from unittest import mock

from automations.blueink_docs import run, slack_post

DAY = dt.date(2026, 11, 23)
ROWS = [
    ["2026-11-09 07:48", "D2D OBCL 11.9", "Milandi Koch", "m@x.com", "atc9wTCcuG", "sent"],
    ["2026-11-23 09:33", "D2D OBCL 11.23", "Haley Paul", "h@x.com", "1B9NcdkULD", "sent"],
    ["2026-11-23 09:33", "D2D OBCL 11.23", "Kip Wilson", "k@x.com", "OCoVkCwNVU", "completed"],
    ["2026-11-23 09:40", "D2D OBCL 11.23", "No Receipt", "n@x.com", "", "failed"],
    ["2026-11-23 10:00", "D2D OBCL 11.16", "Other Week", "o@x.com", "Zz9", "sent"],
]


class SentToday(unittest.TestCase):
    def test_only_todays_rows_with_a_bundle_id_count(self):
        self.assertEqual(run.sent_today(ROWS, "", DAY),
                         ["Haley Paul", "Kip Wilson", "Other Week"])

    def test_a_tab_narrows_it_to_that_week(self):
        self.assertEqual(run.sent_today(ROWS, "D2D OBCL 11.23", DAY),
                         ["Haley Paul", "Kip Wilson"])

    def test_short_rows_do_not_crash(self):
        self.assertEqual(run.sent_today([["2026-11-23 09:00"]], "", DAY), [])


class PostSentSummary(unittest.TestCase):
    def test_posts_the_count_and_sends_nothing_else(self):
        with mock.patch.object(run, "sent_today", return_value=["A", "B"]), \
                mock.patch.object(slack_post, "post") as post:
            self.assertEqual(run._post_sent_summary(ROWS, "", post=True), 0)
        post.assert_called_once_with(2, [], dry_run=False)

    def test_without_slack_it_is_a_preview(self):
        with mock.patch.object(run, "sent_today", return_value=["A"]), \
                mock.patch.object(slack_post, "post") as post:
            run._post_sent_summary(ROWS, "", post=False)
        post.assert_called_once_with(1, [], dry_run=True)

    def test_nothing_sent_today_posts_nothing(self):
        with mock.patch.object(run, "sent_today", return_value=[]), \
                mock.patch.object(slack_post, "post") as post:
            self.assertEqual(run._post_sent_summary(ROWS, "", post=True), 1)
        post.assert_not_called()

    def test_the_body_reads_as_sent(self):
        body = slack_post.build_thread(11, [])
        self.assertIn("*11* new starts sent", body)
        self.assertIn("*0* failed to send", body)


if __name__ == "__main__":
    unittest.main()
