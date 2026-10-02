"""Revenue Board before 06:25 with no rows for yesterday = DEFER, not a miss.

10/2 ticket: the 05:23 pass raised a plain RuntimeError, the runner counted it
as a real miss and paged #claudecorrections, while the 7:45 pass would have
posted it anyway. OrderLogNotFresh routes it through the deferral path, which
holds the alert until after the floor pass."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.b2b_metrics import capture
from automations.vantura_revenue_board import run as rb


class RevenueBoardDefers(unittest.TestCase):
    def test_not_ready_raises_orderlog_not_fresh(self):
        tmp = Path(tempfile.mkdtemp())
        upto = dt.date.today() - dt.timedelta(days=1)
        day_before = upto - dt.timedelta(days=1)
        per_rep = {"Rep A": {"days": {day_before: 250.0}, "elig": 1, "payable": 1}}
        src = tmp / "orderlog.csv"
        src.write_text("x")
        with mock.patch.object(rb, "OUT_DIR", tmp), \
             mock.patch.object(rb, "week_of", return_value=upto), \
             mock.patch.object(rb, "load_priced", return_value=(per_rep, [])), \
             mock.patch.object(rb, "att_day_ready", return_value=False), \
             mock.patch.object(rb, "render") as render, \
             mock.patch("automations.captainship_boards.run.pull_orderlog",
                        side_effect=lambda m, u, p: Path(p).write_text("x")):
            with self.assertRaises(capture.OrderLogNotFresh) as cm:
                capture.revenue_board_image(None, tmp, log=lambda *a: None)
        self.assertEqual(cm.exception.need, upto)
        self.assertEqual(cm.exception.maxd, day_before)
        render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
