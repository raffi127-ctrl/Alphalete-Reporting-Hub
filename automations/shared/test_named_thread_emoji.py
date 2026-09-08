"""An emoji in a named-thread title must not stop us finding today's header.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_named_thread_emoji

WHAT WENT WRONG (Megan 2026-09-07: "this shouldn't have 2 threads in the 11280
channel", then five of them).

digi_docs posts its daily header as '*🗂️ Digi Docs — September 7th 2026*'.
Slack STORES that text as ':card_index_dividers: Digi Docs — September 7th
2026' — the literal emoji is never what conversations_history reads back. So
find_named_thread_ts looked for a substring containing the literal emoji,
never found it, and ensure_named_thread did the only thing it can do when
today's header is missing: post one.

The send pass is a five-minute tick, so that repeated all afternoon — a new
identical thread every time anything needed to say something, with the day's
replies scattered across all of them and no single thread showing the run.

The fix matches on the header's WORDS plus its date, with any leading emoji
(literal or :shortcode:) removed from both sides. The dated suffix is what
carries the specificity, so the negatives below still have to hold.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.shared import slack_metrics_post as smp

TODAY = dt.date(2026, 9, 7)
TITLE = "🗂️ Digi Docs"


class _Client:
    """Stands in for the Slack client; returns one message."""

    def __init__(self, text):
        self.text = text

    def conversations_history(self, **kw):
        return {"messages": [{"text": self.text, "ts": "111.222"}]}


def _find(stored, title=TITLE):
    return smp.find_named_thread_ts(_Client(stored), title, TODAY,
                                    channel_id="C1")


class EmojiHeadersAreFound(unittest.TestCase):

    def test_the_shortcode_slack_actually_stores(self):
        """The real case. This is what broke."""
        self.assertEqual("111.222", _find(
            "*:card_index_dividers: Digi Docs — September 7th 2026*"))

    def test_a_literal_emoji_still_matches(self):
        """Some clients do preserve it — both spellings must work."""
        self.assertEqual("111.222",
                         _find("*🗂️ Digi Docs — September 7th 2026*"))

    def test_a_title_with_no_emoji_is_unaffected(self):
        self.assertEqual("111.222", _find(
            "*Blueink Status Update — September 7th 2026*",
            title="Blueink Status Update"))


class ItStillRefusesTheWrongHeader(unittest.TestCase):
    """Stripping the emoji must not make the match sloppy."""

    def _refuses(self, stored, title=TITLE):
        with self.assertRaises(smp.SlackPostError):
            _find(stored, title)

    def test_another_report_todays_header(self):
        self._refuses("*:memo: Blueink Status Update — September 7th 2026*")

    def test_our_own_header_from_yesterday(self):
        self._refuses("*:card_index_dividers: Digi Docs — September 6th 2026*")

    def test_a_longer_title_that_starts_the_same(self):
        """'Digi Docs — …' must not match 'Digi Docs Extra — …'."""
        self._refuses(
            "*:card_index_dividers: Digi Docs Extra — September 7th 2026*")

    def test_a_reply_that_merely_mentions_the_name(self):
        """A refusal posted INTO the thread says 'Digi Docs — could not send'.
        Without the date it is not a header and must never be taken for one."""
        self._refuses("*Digi Docs — could not send*\n• somebody: not found")


class StripLeadEmoji(unittest.TestCase):

    def test_shapes(self):
        s = smp._strip_lead_emoji
        self.assertEqual("Digi Docs", s("🗂️ Digi Docs"))
        self.assertEqual("Digi Docs", s(":card_index_dividers: Digi Docs"))
        self.assertEqual("Digi Docs", s("Digi Docs"))
        self.assertEqual("Total Knocks", s(":door: Total Knocks"))

    def test_it_never_empties_a_string(self):
        """An emoji-only title keeps its emoji rather than becoming ''."""
        self.assertTrue(smp._strip_lead_emoji("🗂️"))


if __name__ == "__main__":
    unittest.main()
