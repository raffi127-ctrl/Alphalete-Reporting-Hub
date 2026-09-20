"""python -m unittest automations.pay_period_office_info.test_run"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from automations.pay_period_office_info import run
from automations.pay_period_office_info.render import render
from automations.shared.pay_period import pay_weeks


class Blocks(unittest.TestCase):
    def test_image_block_points_at_the_upload(self):
        blocks = run._blocks("F123", date(2026, 10, 1))
        self.assertEqual(blocks[1]["slack_file"], {"id": "F123"})
        self.assertIn("Pay Period", blocks[0]["text"]["text"])


class Image(unittest.TestCase):
    def test_draws(self):
        weeks = pay_weeks(date(2026, 10, 1), run.WEEKS_BACK, run.WEEKS_TOTAL)
        self.assertEqual(len(weeks), run.WEEKS_TOTAL)
        self.assertEqual(weeks[0][0], date(2026, 8, 30))
        with tempfile.TemporaryDirectory() as tmp:
            out = render(weeks, Path(tmp) / "p.png", date(2026, 10, 1))
            self.assertGreater(out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
