"""verizon_wait.pending: the Org email waits for Verizon until 9:45 CT."""
import datetime as dt
import unittest
from unittest import mock

from automations.org_sales_board import verizon_wait as W

DAY = dt.date(2026, 10, 28)


def at(h, m=0):
    return dt.datetime.combine(DAY, dt.time(h, m))


class _Base(unittest.TestCase):
    def use(self, patcher):          # enterContext is 3.11+; runners are 3.9
        out = patcher.start()
        self.addCleanup(patcher.stop)
        return out

    def patch(self, blank, pdf, top_off_fills=True):
        state = {"blank": blank}
        top = mock.Mock(side_effect=lambda: state.update(blank=not top_off_fills and blank))
        self.use(mock.patch.object(W, "_blank_yesterday", lambda d: state["blank"]))
        self.use(mock.patch.object(W, "_todays_pdf_in", lambda d: pdf))
        self.use(mock.patch.object(W, "top_off", top))
        return top


class PendingTest(_Base):
    def test_filled_goes(self):
        self.patch(blank=False, pdf=False)
        self.assertIsNone(W.pending(DAY, at(8)))

    def test_blank_no_pdf_waits(self):
        top = self.patch(blank=True, pdf=False)
        self.assertIn("not in yet", W.pending(DAY, at(9, 20)))
        top.assert_not_called()

    def test_pdf_in_tops_off_and_goes(self):
        top = self.patch(blank=True, pdf=True)
        self.assertIsNone(W.pending(DAY, at(9, 35)))
        top.assert_called_once()

    def test_top_off_still_blank_keeps_waiting(self):
        self.patch(blank=True, pdf=True, top_off_fills=False)
        self.assertIsNotNone(W.pending(DAY, at(9, 35)))

    def test_past_deadline_sends_anyway(self):
        self.patch(blank=True, pdf=False)
        self.assertIsNone(W.pending(DAY, at(9, 45)))

    def test_old_day_never_waits(self):
        self.patch(blank=True, pdf=False)
        self.assertIsNone(W.pending(DAY - dt.timedelta(days=1), at(8)))

    def test_read_error_does_not_wait(self):
        self.use(mock.patch.object(
            W, "_blank_yesterday", mock.Mock(side_effect=RuntimeError("x"))))
        self.assertIsNone(W.pending(DAY, at(8)))


class WaitingTest(_Base):
    """The Slack post's read-only check: waits on the same rule, never writes."""

    def test_blank_waits_without_top_off(self):
        top = self.patch(blank=True, pdf=True)
        self.assertIn("not on the board", W.waiting(DAY, at(9, 30)))
        top.assert_not_called()

    def test_filled_posts(self):
        self.patch(blank=False, pdf=False)
        self.assertIsNone(W.waiting(DAY, at(7, 5)))

    def test_past_deadline_posts_anyway(self):
        self.patch(blank=True, pdf=False)
        self.assertIsNone(W.waiting(DAY, at(9, 45)))

    def test_read_error_posts(self):
        self.use(mock.patch.object(
            W, "_blank_yesterday", mock.Mock(side_effect=RuntimeError("x"))))
        self.assertIsNone(W.waiting(DAY, at(8)))


if __name__ == "__main__":
    unittest.main()
