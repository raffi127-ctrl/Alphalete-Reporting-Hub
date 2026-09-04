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
it delivered. `files.info` on F0BUK46L7KR fails outright — that file does not
exist — while its 60-day sibling from the same loop is in the thread. Slack
accepted the upload; the message never materialised. Wireless posted all four
of its boards in the same loop, so it was one image, not the run.

Two separate defects, and the second is the one that let it run for a day:

  1. the post certified itself off the RETURN VALUE, never off the thread;
  2. nothing declared how many boards the report owes. The day-orchestrator
     manifest records ONE section, "churn", for all EIGHT images and judges it
     by the subprocess exit code — so 7 of 8 is a clean run and no bucket is
     nameable as missing.

Same family as the empty-pull-certifies-as-success bugs.

The check READS THE THREAD (conversations_replies), the same call
`wait_for_share` uses: it tests what a reader actually sees and needs no
files:read scope. The tri-state return is the load-bearing part — see
AnUnanswerableCheckNeverInventsAMiss.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import slack_metrics_post as smp

CH = "C068PH3RFSM"          # #alphalete-sales
TS = "1788516839.407259"    # the 2026-09-04 Metrics thread


def _client(messages=None, raises=False):
    """A stand-in for the Slack client's conversations_replies."""
    c = mock.Mock()
    if raises:
        c.conversations_replies.side_effect = RuntimeError("channel_not_found")
    else:
        c.conversations_replies.return_value = {"messages": messages or []}
    return c


def _msg_with_file(file_id):
    return {"text": "", "files": [{"id": file_id}]}


class ADeliveredBoardIsSeen(unittest.TestCase):

    def test_the_file_id_in_the_thread_is_landed(self):
        # F0BV0EHAMQS — the 60-day board that really is in the thread.
        c = _client([_msg_with_file("F0BV0EHAMQS")])
        self.assertIs(smp.file_landed_in_thread(c, "F0BV0EHAMQS", CH, TS), True)

    def test_the_comment_is_the_fallback_when_no_id_came_back(self):
        """Same fallback wait_for_share uses — an upload response with no id
        would otherwise be unverifiable forever."""
        c = _client([{"text": "🌐 New Internet Churn — 30 Day", "files": []}])
        self.assertIs(
            smp.file_landed_in_thread(
                c, "", CH, TS, comment="🌐 New Internet Churn — 30 Day"), True)

    def test_it_stops_polling_as_soon_as_it_lands(self):
        c = _client([_msg_with_file("F")])
        smp.file_landed_in_thread(c, "F", CH, TS, tries=4, delay=0)
        self.assertEqual(c.conversations_replies.call_count, 1)


class AnUndeliveredBoardIsCaught(unittest.TestCase):
    """THE BUG — the thread read succeeds and the image simply is not there."""

    def test_an_empty_thread_is_not_landed(self):
        c = _client([])
        self.assertIs(smp.file_landed_in_thread(c, "F0BUK46L7KR", CH, TS,
                                                tries=2, delay=0), False)

    def test_other_boards_present_but_not_this_one(self):
        """The exact 2026-09-04 shape: 0-30, 60 and 90 landed, 30 did not."""
        c = _client([_msg_with_file("F0C0ERUDXDE"),
                     _msg_with_file("F0BV0EHAMQS"),
                     _msg_with_file("F0BUU7WPRM1")])
        self.assertIs(smp.file_landed_in_thread(c, "F0BUK46L7KR", CH, TS,
                                                tries=2, delay=0), False)

    def test_it_polls_before_giving_up(self):
        """The message is created asynchronously after the upload returns, so a
        single instant check would invent misses."""
        c = _client([])
        smp.file_landed_in_thread(c, "F", CH, TS, tries=3, delay=0)
        self.assertEqual(c.conversations_replies.call_count, 3)


class AnUnanswerableCheckNeverInventsAMiss(unittest.TestCase):
    """A check we cannot RUN must not become a failure — that would page every
    morning on a token that can't read the channel, which is worse than the
    silence it replaces. False means 'we looked and it wasn't there'."""

    def test_an_api_error_is_None_not_False(self):
        c = _client(raises=True)
        self.assertIsNone(smp.file_landed_in_thread(c, "F", CH, TS,
                                                    tries=2, delay=0))

    def test_nothing_to_match_on_is_None(self):
        self.assertIsNone(smp.file_landed_in_thread(_client(), "", CH, TS))

    def test_no_thread_ts_is_None(self):
        """A top-level post has no thread to look in."""
        self.assertIsNone(smp.file_landed_in_thread(_client(), "F", CH, ""))


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
