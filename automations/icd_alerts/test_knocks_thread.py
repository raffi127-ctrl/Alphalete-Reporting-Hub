"""THE BOARDS GO IN THE ROOM, ONE POST EACH.

They were threaded for a day. On 2026-09-23 a 30-minute cadence was burying
each office's own conversation under near-identical images, so each office got
one dated header and its boards as replies. The rooms did not want it (Megan,
2026-09-24: "people don't like this where the knock boards are in the thread")
— a board inside a thread is a board somebody has to go looking for, and these
are glanced at, not read.

These pin the reverted shape so it does not drift back:
  * a board is a CHANNEL post — no thread_ts, no dated header;
  * the caption still says what the board is and when it was drawn, because at
    channel level that line is the only thing dating the post;
  * RAF'S IS NOT THIS. gap_alerts keeps its parent and per-board replies in
    #alphalete-lvl1-chat, which predates all of the above and stays.
  * CARLOS'S #a-players-b2b IS THE ONE EXCEPTION (2026-09-24, same day):
    Carlos asked "can they just go into one thread please!" and Megan, in
    the reply: "please just make that for Carlos". Only the rooms listed in
    K.THREADED_CHANNELS thread; every other room is still a channel post.
"""
from __future__ import annotations

import datetime as dt
import inspect
import unittest
from unittest import mock

from automations.icd_alerts import knocks_post as K


class _Office:
    key, label, campaign = "ryan", "Ryan's Local Office", "b2b_box"


class _Client:
    def __init__(self):
        self.calls = []

    def files_upload_v2(self, **kw):
        self.calls.append(kw)
        return {"ok": True}


class ABoardIsAChannelPost(unittest.TestCase):
    def _upload(self):
        client = _Client()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client):
            K._upload("C1", ["a.png", "b.png"], "*Knocks & Dispositions*")
        return client.calls

    def test_nothing_is_posted_into_a_thread(self):
        for call in self._upload():
            self.assertNotIn("thread_ts", call)

    def test_every_board_still_arrives(self):
        """A wireless office gets the board and its Time Gaps twin."""
        self.assertEqual(len(self._upload()), 2)

    def test_only_the_first_board_carries_the_caption(self):
        calls = self._upload()
        self.assertEqual(calls[0]["initial_comment"], "*Knocks & Dispositions*")
        self.assertIsNone(calls[1]["initial_comment"])


class TheCaptionCarriesTheClock(unittest.TestCase):
    def test_it_names_the_report_and_its_time(self):
        """At channel level this line is the only thing dating the post — in a
        thread the parent did that job, which is why the threaded version was
        allowed to shrink to a bare clock."""
        comment = K._comment(_Office(), [], dt.datetime(2026, 9, 24, 11, 4))
        self.assertIn("ranked by total knocks", comment)
        self.assertIn("11:04 AM", comment)


class NoThreadMachineryIsLeftBehind(unittest.TestCase):
    """Half a revert is worse than none: a helper nobody calls is the thing
    somebody wires back up by accident."""

    def test_the_poster_has_no_thread_helpers(self):
        for gone in ("_thread_ts", "_thread_title", "_reply_caption",
                     "_remember_thread", "_remembered_thread"):
            self.assertFalse(hasattr(K, gone), gone)

    def test_the_send_does_not_ask_for_a_thread(self):
        src = inspect.getsource(K.run)
        # THE RULE IS "NO THREAD", not a spelling of the upload call. The
        # third argument stopped being `comment` on 2026-09-24, when the
        # caption became per-room -- Kash's #palace-sales carries the typed
        # gap list in its caption and the other rooms carry the heading
        # alone -- so pinning the literal call failed on a change that has
        # nothing to do with threads.
        self.assertIn('_upload(d["channel_id"], boards,', src)
        self.assertNotIn("thread_ts", src)


class CarlosAPlayersIsTheOneThreadedRoom(unittest.TestCase):
    """One opt-in room, not a second rollout: the list stays Carlos's."""

    def test_only_a_players_is_threaded(self):
        self.assertEqual(K.THREADED_CHANNELS, {"C0AJQA8P716"})

    def test_a_players_boards_land_in_the_day_thread(self):
        client = _Client()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client),              mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread",
                        return_value={"thread_ts": "111.1"}):
            K._upload("C0AJQA8P716", ["a.png", "b.png"], "*Knocks*")
        self.assertEqual([c.get("thread_ts") for c in client.calls],
                         ["111.1", "111.1"])

    def test_no_thread_means_the_board_still_posts(self):
        client = _Client()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client),              mock.patch("automations.shared.slack_metrics_post."
                        "ensure_named_thread", side_effect=RuntimeError("x")):
            K._upload("C0AJQA8P716", ["a.png"], "*Knocks*")
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("thread_ts", client.calls[0])

    def test_the_header_has_no_ampersand(self):
        """Slack stores '&' as '&amp;': the header would never be found again
        and every tick would open a new thread."""
        self.assertNotIn("&", K.THREAD_TITLE)


class RafsBoardIsUntouched(unittest.TestCase):
    """His room asked for the thread, it predates the ICD poster, and reverting
    theirs must not quietly revert his."""

    def test_gap_alerts_still_opens_a_daily_thread(self):
        from automations.gap_alerts import run as G
        self.assertTrue(hasattr(G, "_daily_thread_ts"))
        self.assertIn("thread_ts", inspect.signature(G.post_slack).parameters)


if __name__ == "__main__":
    unittest.main()
