"""One Slack post a day, every later board a reply inside it.

    python -m unittest automations.gap_alerts.test_slack_thread

Megan 2026-09-20: *"can we do one post that's called Knocks and Dispositions...
it only needs to tag them one time... versus the chat being filled up."*

The failures these guard against are the two that would be invisible: a parent
re-posted on every tick (the chat fills up anyway, and everyone gets re-tagged
every 30 minutes), and a parent that failed to post taking the day's boards
down with it.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.gap_alerts import config as C
from automations.gap_alerts import run as R

DAY = dt.date(2026, 9, 21)
CFG = {"key": "rafael", "name": "Rafael Hidalgo", "label": ""}
CHANNEL = "C09JG28CD27"


class _Store:
    """Stands in for the on-disk state file."""

    def __init__(self, data=None):
        self.data = data or {}

    def patches(self):
        return [mock.patch.object(R, "_state", lambda: self.data),
                mock.patch.object(R, "_save_state", self.data.update)]


class ThreadParentTests(unittest.TestCase):
    def _run(self, store, client, cfg=CFG, day=DAY, dry_run=False):
        ps = store.patches() + [
            mock.patch("automations.shared.slack_metrics_post._client",
                       lambda: client),
            mock.patch.object(R, "_log", lambda *_: None)]
        for p in ps:
            p.start()
        try:
            return R._daily_thread_ts(cfg, CHANNEL, day, dry_run=dry_run)
        finally:
            for p in reversed(ps):
                p.stop()

    def _client(self, ts="1700.1"):
        cli = mock.Mock()
        cli.chat_postMessage.return_value = {"ts": ts}
        return cli

    def test_the_first_board_of_the_day_opens_the_thread(self):
        store, cli = _Store(), self._client()
        self.assertEqual(self._run(store, cli), "1700.1")
        self.assertEqual(cli.chat_postMessage.call_count, 1)
        text = cli.chat_postMessage.call_args.kwargs["text"]
        self.assertIn(C.CARD_TITLE.title(), text)

    def test_every_later_board_reuses_it_and_re_tags_nobody(self):
        store, cli = _Store(), self._client()
        first = self._run(store, cli)
        again = self._run(store, cli)
        self.assertEqual(first, again)
        self.assertEqual(cli.chat_postMessage.call_count, 1,
                         "a second parent would re-ping every leader")

    def test_tomorrow_opens_a_fresh_thread(self):
        """The tag list is re-read then, so a rep terminated today is not
        tagged tomorrow."""
        store, cli = _Store(), self._client()
        self._run(store, cli)
        cli.chat_postMessage.return_value = {"ts": "1800.2"}
        self.assertEqual(self._run(store, cli, day=DAY + dt.timedelta(days=1)),
                         "1800.2")

    def test_another_office_in_the_same_room_gets_its_own_thread(self):
        store, cli = _Store(), self._client()
        self._run(store, cli)
        cli.chat_postMessage.return_value = {"ts": "1900.3"}
        other = dict(CFG, key="calvin")
        self.assertEqual(self._run(store, cli, cfg=other), "1900.3")

    def test_a_failed_parent_does_not_stop_the_board(self):
        """No ts means the board posts at channel level — the old behaviour.
        A board that does not arrive at all is the failure that matters."""
        store, cli = _Store(), self._client()
        cli.chat_postMessage.side_effect = RuntimeError("channel_not_found")
        self.assertEqual(self._run(store, cli), "")
        self.assertEqual(store.data.get("_slack_thread", {}), {})

    def test_a_preview_posts_nothing_and_stores_nothing(self):
        """A dry run that stamped state would make the real run think the
        parent already existed, and the day would have no thread at all."""
        store, cli = _Store(), self._client()
        self.assertEqual(self._run(store, cli, dry_run=True), "")
        cli.chat_postMessage.assert_not_called()
        self.assertEqual(store.data.get("_slack_thread", {}), {})


class CaptionTests(unittest.TestCase):
    def _caption(self, **kw):
        from pathlib import Path
        return R.post_slack(CFG, Path("board.png"), "4:45 PM", DAY,
                            channel=CHANNEL, dry_run=True, **kw)["comment"]

    def test_a_reply_is_labelled_with_its_own_time(self):
        """Megan: 'every time it's posted is a new reply in the thread labeled
        with that time'. Twenty near-identical boards in one thread are only
        told apart by the clock."""
        self.assertEqual(self._caption(thread_ts="1700.1"), "*4:45 PM*")

    def test_the_parent_header_carries_no_time(self):
        """It is written once, at 1:30pm, and read all day."""
        self.assertNotIn("4:45", R._parent_text(""))
        self.assertEqual(R._parent_text(""),
                         "*Knocks & Dispositions · ranked by total knocks*")

    def test_the_parent_header_carries_the_tags_under_it(self):
        text = R._parent_text("<@U1> <@U2>")
        self.assertTrue(text.startswith("*Knocks & Dispositions"))
        self.assertIn("<@U1> <@U2>", text.split("\n", 1)[1])

    def test_a_channel_level_post_is_unchanged_but_for_the_time(self):
        """Offices without a thread keep the caption they have had all along —
        minus the clock the board's own title band already carries."""
        cap = self._caption()
        self.assertIn("Knocks & Dispositions", cap)
        self.assertIn("ranked by total knocks", cap)
        self.assertNotIn("4:45", cap)

    def test_the_thread_ts_reaches_the_upload(self):
        from pathlib import Path
        cli = mock.Mock()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        lambda: cli):
            R.post_slack(CFG, Path("board.png"), "4:45 PM", DAY,
                         channel=CHANNEL, dry_run=False, thread_ts="1700.1")
        self.assertEqual(
            cli.files_upload_v2.call_args.kwargs["thread_ts"], "1700.1")

    def test_no_thread_ts_key_when_there_is_no_thread(self):
        """files_upload_v2 with thread_ts='' is not 'post to the channel'."""
        from pathlib import Path
        cli = mock.Mock()
        with mock.patch("automations.shared.slack_metrics_post._client",
                        lambda: cli):
            R.post_slack(CFG, Path("board.png"), "4:45 PM", DAY,
                         channel=CHANNEL, dry_run=False)
        self.assertNotIn("thread_ts", cli.files_upload_v2.call_args.kwargs)


class RafDestinationTests(unittest.TestCase):
    def test_rafs_slack_channel_threads_and_the_imessage_rooms_do_not(self):
        dests = C.destinations(C.RAF)
        slack = [d for d in dests if d["kind"] == "slack"]
        self.assertEqual(len(slack), 1)
        self.assertTrue(slack[0].get("thread_daily"))
        for d in dests:
            if d["kind"] == "imessage":
                self.assertFalse(d.get("thread_daily"),
                                 "iMessage has no threads")

    def test_only_raf_tags_leaders(self):
        """gap_alerts.leaders reads RAF'S sales board — another office turning
        this on would @-ping his leaders into its own room."""
        tagging = [o["key"] for o in C.OFFICES if o.get("leader_tags")]
        self.assertEqual(tagging, ["rafael"])


if __name__ == "__main__":
    unittest.main()
