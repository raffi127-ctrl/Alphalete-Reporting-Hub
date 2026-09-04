""""Slack said ok" is not "the board is in the thread".

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.churn.test_delivery_verified

WHAT THIS GUARDS (2026-09-04). Dylan Twaddle read the Metrics thread and asked
why there was a 0-30, a 60 and a 90 New Internet Churn board but no 30. Nothing
had alerted. The run log said the opposite of what the thread showed:

    0-30-day: posted (file=F0C0ERUDXDE)
    30-day:   posted (file=F0BUK46L7KR)   <- not in the thread
    60-day:   posted (file=F0BV0EHAMQS)
    90-day:   posted (file=F0BUU7WPRM1)

`files_upload_v2` had returned ok WITH a file id, so every layer above counted
it delivered. `files.info` on F0BUK46L7KR fails — that file does not exist —
while its 60-day sibling from the same loop is there with a share into
C068PH3RFSM on the right thread_ts. Slack accepted the upload; the message never
materialised.

Two separate defects, and the second is the one that let it run for a day:

  1. the post certified itself off the RETURN VALUE, never off the thread;
  2. nothing declared how many boards the report owes. The day-orchestrator
     manifest records ONE section, "churn", for all EIGHT images and judges it
     by the subprocess exit code — so 7 of 8 is a clean run and no bucket is
     nameable as missing.

Same family as the empty-pull-certifies-as-success bugs.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import slack_metrics_post as smp

CH = "C068PH3RFSM"          # #alphalete-sales
TS = "1788516839.407259"    # the 2026-09-04 Metrics thread


def _client(shares=None, raises=False):
    c = mock.Mock()
    if raises:
        c.files_info.side_effect = RuntimeError("file_not_found")
    else:
        c.files_info.return_value = {"file": {"shares": shares or {}}}
    return c


def _share(channel=CH, thread_ts=TS, bucket="private"):
    return {bucket: {channel: [{"ts": "1.1", "thread_ts": thread_ts}]}}


class ADeliveredFileIsSeen(unittest.TestCase):

    def test_a_share_on_the_right_thread_is_landed(self):
        # F0BV0EHAMQS, the 60-day board that really is in the thread.
        c = _client(_share())
        self.assertIs(smp.file_landed_in_thread(c, "F0BV0EHAMQS", CH, TS), True)

    def test_a_public_share_counts_too(self):
        c = _client(_share(bucket="public"))
        self.assertIs(smp.file_landed_in_thread(c, "F", CH, TS), True)

    def test_it_stops_polling_as_soon_as_it_lands(self):
        c = _client(_share())
        smp.file_landed_in_thread(c, "F", CH, TS, tries=4, delay=0)
        self.assertEqual(c.files_info.call_count, 1)


class AnUndeliveredFileIsCaught(unittest.TestCase):
    """THE BUG."""

    def test_no_shares_at_all_is_not_landed(self):
        c = _client({})
        self.assertIs(smp.file_landed_in_thread(c, "F0BUK46L7KR", CH, TS,
                                                tries=2, delay=0), False)

    def test_a_share_in_the_WRONG_thread_is_not_landed(self):
        c = _client(_share(thread_ts="9999.9999"))
        self.assertIs(smp.file_landed_in_thread(c, "F", CH, TS,
                                                tries=2, delay=0), False)

    def test_a_share_in_another_channel_is_not_landed(self):
        c = _client(_share(channel="C_SOMEWHERE_ELSE"))
        self.assertIs(smp.file_landed_in_thread(c, "F", CH, TS,
                                                tries=2, delay=0), False)


class AnUnanswerableCheckNeverInventsAMiss(unittest.TestCase):
    """A check we cannot run must not become a failure — that would page every
    morning on a token without files:read, which is worse than the silence it
    replaces."""

    def test_an_api_error_is_None_not_False(self):
        c = _client(raises=True)
        self.assertIsNone(smp.file_landed_in_thread(c, "F", CH, TS,
                                                    tries=2, delay=0))

    def test_no_file_id_is_None(self):
        self.assertIsNone(smp.file_landed_in_thread(_client(), "", CH, TS))


class OnlyAnExplicitFalseCountsAsAMiss(unittest.TestCase):
    """The rule the churn runner applies to `landed`. Pinned here because
    getting it backwards turns an unverifiable morning into eight false
    alarms."""

    @staticmethod
    def _is_miss(result: dict) -> bool:
        return (not result.get("ok", True)) or result.get("landed") is False

    def test_the_missing_30_day_board_is_a_miss(self):
        self.assertTrue(self._is_miss({"ok": True, "landed": False}))

    def test_a_delivered_board_is_not(self):
        self.assertFalse(self._is_miss({"ok": True, "landed": True}))

    def test_unverifiable_is_not_a_miss(self):
        self.assertFalse(self._is_miss({"ok": True, "landed": None}))

    def test_a_hard_upload_failure_still_is(self):
        self.assertTrue(self._is_miss({"ok": False, "landed": None}))


if __name__ == "__main__":
    unittest.main()
