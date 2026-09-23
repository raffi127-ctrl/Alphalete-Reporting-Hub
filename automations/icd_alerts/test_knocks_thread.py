"""ONE HEADER A DAY PER OFFICE, EVERY BOARD UNDER IT.

Megan, 2026-09-23, looking at #box-leaders: Ryan's room had eight near-identical
knocks boards at channel level before lunch -- "it's really clogging up the
chats". The fix is the one Raf's board already uses: a parent post that says
once what this is, and one reply per board carrying its own clock.

What these pin down:
  * the parent names the office AND its campaign, and carries no clock;
  * a board in the thread says its time and nothing else;
  * the picture never gets broadcast back to the channel;
  * a thread that cannot be opened costs the room its header, never its board.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import knocks_post as K


class _Office:
    def __init__(self, key="ryan", label="Ryan's Local Office",
                 campaign="b2b_box"):
        self.key = key
        self.label = label
        self.campaign = campaign


class TheDaysHeader(unittest.TestCase):
    def test_it_names_the_office_and_the_campaign(self):
        """Carlos runs two campaigns into one room. Two threads headed only
        'Knocks & Dispositions' are two identical lines and the only way to
        tell them apart is to know his rep list by heart."""
        title = K._thread_title(_Office())
        self.assertIn("Ryan's Local Office", title)
        self.assertIn("B2B Box", title)

    def test_it_carries_no_clock(self):
        """It is written at the day's first board and is still at the top of
        the thread at 9pm. A time on it is wrong for every reply under it."""
        title = K._thread_title(_Office())
        self.assertNotIn("AM", title)
        self.assertNotIn("PM", title)

    def test_two_campaigns_in_one_room_are_two_threads(self):
        day = dt.date(2026, 9, 23)
        box = K._thread_key("C1", _Office(campaign="b2b_box"), day)
        att = K._thread_key("C1", _Office(campaign="b2b_att"), day)
        self.assertNotEqual(box, att)

    def test_one_office_in_two_rooms_is_two_threads(self):
        day = dt.date(2026, 9, 23)
        self.assertNotEqual(K._thread_key("C1", _Office(), day),
                            K._thread_key("C2", _Office(), day))

    def test_yesterdays_thread_is_not_todays(self):
        self.assertNotEqual(K._thread_key("C1", _Office(), dt.date(2026, 9, 22)),
                            K._thread_key("C1", _Office(), dt.date(2026, 9, 23)))


class ABoardInTheThreadSaysItsTime(unittest.TestCase):
    def test_the_caption_is_the_clock_and_nothing_else(self):
        """The report's name and what it is ranked by are in the parent, said
        once. Repeating them on twenty replies is the same clutter, one level
        down. The clock is what tells 10:32's board from 11:04's."""
        caption = K._reply_caption(dt.datetime(2026, 9, 23, 11, 4))
        self.assertEqual(caption, "*11:04 AM*")

    def test_the_channel_level_caption_still_carries_the_heading(self):
        """When there is no thread the post is on its own in the room, so it
        still has to say what it is."""
        comment = K._comment(_Office(), [], dt.datetime(2026, 9, 23, 11, 4))
        self.assertIn("ranked by total knocks", comment)
        self.assertIn("11:04 AM", comment)


class _Client:
    def __init__(self):
        self.calls = []

    def files_upload_v2(self, **kw):
        self.calls.append(kw)
        return {"ok": True}


class TheUpload(unittest.TestCase):
    def _upload(self, thread_ts):
        client = _Client()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client):
            K._upload("C1", ["a.png", "b.png"], "*11:04 AM*",
                      thread_ts=thread_ts)
        return client.calls

    def test_every_board_goes_into_the_thread(self):
        """A wireless office gets a pair -- the board and its Time Gaps twin --
        and a twin left at channel level is exactly the clutter being removed."""
        calls = self._upload("1758640000.1")
        self.assertEqual([c.get("thread_ts") for c in calls],
                         ["1758640000.1", "1758640000.1"])

    def test_only_the_first_board_carries_the_caption(self):
        calls = self._upload("1758640000.1")
        self.assertEqual(calls[0]["initial_comment"], "*11:04 AM*")
        self.assertIsNone(calls[1]["initial_comment"])

    def test_the_picture_is_never_broadcast_back_to_the_channel(self):
        """reply_broadcast would put the board in the room as well, which is
        the whole thing the thread exists to stop."""
        for call in self._upload("1758640000.1"):
            self.assertNotIn("reply_broadcast", call)

    def test_no_thread_means_the_old_channel_level_post(self):
        for call in self._upload(""):
            self.assertNotIn("thread_ts", call)


class AThreadThatCannotBeOpened(unittest.TestCase):
    """The room loses its header, never its board. A picture in the wrong place
    is recoverable; a board that never arrives is the failure that matters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(K, "OUT_DIR", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_slack_failure_returns_no_thread_rather_than_raising(self):
        said = []
        with mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread", side_effect=RuntimeError("nope")):
            ts = K._thread_ts("C1", _Office(), dt.date(2026, 9, 23),
                              log=said.append)
        self.assertEqual(ts, "")
        self.assertTrue(any("channel" in s for s in said), said)

    def test_a_failure_is_not_remembered_as_a_thread(self):
        with mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread", side_effect=RuntimeError("nope")):
            K._thread_ts("C1", _Office(), dt.date(2026, 9, 23), log=lambda *_: None)
        self.assertEqual(K._remembered_thread(
            K._thread_key("C1", _Office(), dt.date(2026, 9, 23))), "")


class TheThreadIsRememberedLocally(unittest.TestCase):
    """ensure_named_thread finds the header by reading the channel, which is
    right after a restart but reads at most 200 messages back from midnight. In
    a busy room a morning header can fall out of that window by the afternoon,
    and the miss reads as 'no header today' -- a second thread, with the rest of
    the day's boards split across the two.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(K, "OUT_DIR", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.day = dt.date(2026, 9, 23)

    def test_the_second_board_of_the_day_does_not_ask_slack_again(self):
        with mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread",
                        return_value={"thread_ts": "111.2"}) as ensure:
            first = K._thread_ts("C1", _Office(), self.day)
            second = K._thread_ts("C1", _Office(), self.day)
        self.assertEqual((first, second), ("111.2", "111.2"))
        self.assertEqual(ensure.call_count, 1)

    def test_the_header_is_asked_for_in_the_offices_own_room(self):
        with mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread",
                        return_value={"thread_ts": "111.2"}) as ensure:
            K._thread_ts("C1", _Office(), self.day)
        self.assertEqual(ensure.call_args.kwargs.get("channel_id"), "C1")

    def test_yesterdays_note_is_not_carried_forward(self):
        K._remember_thread(K._thread_key("C1", _Office(), dt.date(2026, 9, 22)),
                           "000.1")
        K._remember_thread(K._thread_key("C1", _Office(), self.day), "111.2")
        kept = json.loads((Path(self.tmp.name) / ".threads.json").read_text())
        self.assertEqual(list(kept.values()), ["111.2"])


class TheBoardIsPostedIntoTheThread(unittest.TestCase):
    """The wiring, not just the pieces: run() has to ask for the thread and hand
    the reply caption to the upload, or every board is still a channel post."""

    def test_the_send_asks_for_todays_thread(self):
        import inspect
        src = inspect.getsource(K.run)
        self.assertIn("_thread_ts(d[\"channel_id\"], office, day", src)
        self.assertIn("thread_ts=ts", src)
        self.assertIn("_reply_caption(now) if ts else comment", src)


if __name__ == "__main__":
    unittest.main()
