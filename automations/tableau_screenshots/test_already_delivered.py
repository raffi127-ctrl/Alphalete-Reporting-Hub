"""The Box catch-up skips the browser when every channel already has Box
(2026-10-28: it queued behind a settle pass for the shared profile and was
killed at 45m, alerting for a board every channel already had). No Slack."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.tableau_screenshots import slack_post as sp

DAY = dt.date(2026, 10, 28)
PAGES = [{"id": "b2b_box"}, {"id": "nds"}]


class AlreadyDelivered(unittest.TestCase):
    def _run(self, posted, *, ts="1.0", orgs=("alphalete",), boom=False):
        def _find(client, ch, today):
            if boom:
                raise RuntimeError("slack read failed")
            return ts, False
        with mock.patch.object(sp.smp, "_client", return_value=object()), \
             mock.patch.object(sp, "tracker_ids_for",
                               return_value=["b2b_box", "nds"]), \
             mock.patch.object(sp, "is_email_org", return_value=False), \
             mock.patch.object(sp, "channels_for", return_value=["C1", "C2"]), \
             mock.patch.object(sp, "find_thread_ts", side_effect=_find), \
             mock.patch.object(sp, "posted_ids", return_value=set(posted)):
            return sp.already_delivered(PAGES, ["b2b_box"], list(orgs), DAY)

    def test_box_everywhere_skips(self):
        self.assertTrue(self._run({"b2b_box", "nds"}))

    def test_box_missing_captures(self):
        self.assertFalse(self._run({"nds"}))

    def test_no_thread_yet_captures(self):
        self.assertFalse(self._run({"b2b_box"}, ts=None))

    def test_unreadable_channel_captures(self):
        self.assertFalse(self._run({"b2b_box"}, boom=True))


if __name__ == "__main__":
    unittest.main()
