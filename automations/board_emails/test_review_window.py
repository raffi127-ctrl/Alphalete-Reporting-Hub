"""The gates read a NARROW window of the review channel — and still see the day.

2026-09-20: Slack kept cutting its own answers off mid-body. Three runs died on
`http.client.IncompleteRead` (~70 KB read of a ~180 KB reply) and the Country
board's review link never reached the channel. Asking for the whole channel
(limit=100) is what made the reply that big, so `_all_posts` now asks only for
the day's window.

What must not break: the window has to contain every post that day could have,
because a post the gate cannot see is a post it will publish a SECOND time —
and with two posts for one day the checker takes the newest, so a checkmark on
the older one silently never sends.
"""
import datetime as dt
import unittest

from automations.board_emails import boards as B
from automations.board_emails import review_gate as bg
from automations.org_sales_board.review_gate import _since

DAY = dt.date(2026, 9, 20)
# Central is UTC-5 in summer, UTC-6 in winter: the earliest a day can start.
EARLIEST_CENTRAL_MIDNIGHT = dt.datetime(2026, 9, 20, 5, tzinfo=dt.timezone.utc)


class TheWindowOpensBeforeTheDay(unittest.TestCase):
    def test_before_central_midnight(self):
        self.assertLess(float(_since(DAY)), EARLIEST_CENTRAL_MIDNIGHT.timestamp())

    def test_with_hours_to_spare_for_dst_and_a_late_rerun(self):
        margin = EARLIEST_CENTRAL_MIDNIGHT.timestamp() - float(_since(DAY))
        self.assertGreater(margin / 3600, 12)

    def test_but_it_is_still_a_window(self):
        """If it reached back days it would be the same fat read as before."""
        margin = EARLIEST_CENTRAL_MIDNIGHT.timestamp() - float(_since(DAY))
        self.assertLess(margin / 3600, 36)

    def test_every_day_gets_its_own(self):
        self.assertNotEqual(_since(DAY), _since(DAY - dt.timedelta(days=1)))


class _FakeClient:
    """Answers like Slack, and records what it was asked for."""

    def __init__(self, messages):
        self.messages = messages
        self.kwargs = None

    def conversations_history(self, **kw):
        self.kwargs = kw
        return {"messages": self.messages}


class TheGateStillFindsTheDay(unittest.TestCase):
    def setUp(self):
        self.board = B.get("country")
        self.title = bg._title(self.board, DAY)

    def _run(self, messages):
        fake = _FakeClient(messages)
        orig = bg._client
        bg._client = lambda: fake
        try:
            return fake, bg._all_posts(self.board, DAY, "C0TEST1234")
        finally:
            bg._client = orig

    def test_it_asks_for_the_days_window(self):
        fake, _ = self._run([])
        self.assertEqual(fake.kwargs.get("oldest"), _since(DAY))

    def test_it_still_matches_the_days_post(self):
        fake, got = self._run([{"ts": "1", "text": f"*{self.title}*\nhttp://x"}])
        self.assertEqual(len(got), 1)

    def test_and_still_ignores_another_gates_post(self):
        _, got = self._run([{"ts": "1", "text": "*Org Sales Board Email — 9/19*"}])
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
