"""A self-sending board email with no review post has nothing to approve, so its
"not sent yet" alert must not ask for a checkmark (Eve 2026-11-09).

    python -m unittest automations.machine_digest.test_auto_send_waiting
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.day_orchestrator import notify
from automations.machine_digest import run as R
from automations.org_sales_board import review_gate as G
from automations.shared import incident_reformat as IR

DAY = dt.date(2026, 11, 9)
ORG = "sales-board-screenshot-email-approved"


class HasNoPost(unittest.TestCase):
    def test_no_post_means_nothing_to_approve(self):
        with mock.patch.object(G, "_find_post", return_value=None):
            self.assertTrue(R._auto_send_has_no_post(ORG, DAY))

    def test_a_held_day_still_asks_for_the_checkmark(self):
        with mock.patch.object(G, "_find_post", return_value={"ts": "1"}):
            self.assertFalse(R._auto_send_has_no_post(ORG, DAY))

    def test_cannot_read_slack_keeps_the_approval_wording(self):
        with mock.patch.object(G, "_find_post", side_effect=RuntimeError):
            self.assertFalse(R._auto_send_has_no_post(ORG, DAY))

    def test_a_gated_email_is_not_affected(self):
        self.assertFalse(R._auto_send_has_no_post("headcount-approved", DAY))


class Wording(unittest.TestCase):
    def test_alert_names_no_approval_and_tags_nobody(self):
        with mock.patch.object(notify, "_corrections_channel", return_value="C1"), \
             mock.patch.object(notify, "_incident_post",
                               return_value=True) as post:
            notify.send_standalone_alert(
                object(), name="Org. Sales Board Email — approved",
                report_id=ORG, kind="AUTO_WAITING", status="not sent yet",
                when="usually starts ~7:00", day="Mon Nov 09")
        kw = post.call_args.kwargs
        self.assertEqual(
            kw["title"],
            "*Org. Sales Board Email* — not sent yet, no approval needed")
        text = " ".join(kw["body"] + kw["details"])
        self.assertNotIn("<@", text)
        self.assertIn("No checkmark needed", text)
        self.assertIsNone(kw["reaction"])

    def test_reformat_pass_leaves_the_title_alone(self):
        text = ("*Org. Sales Board Email* — not sent yet, no approval needed\n\n"
                "_incident · standalone-" + ORG + " · open 2026-11-09_")
        self.assertIsNone(IR._waiting_head(text))


if __name__ == "__main__":
    unittest.main()
