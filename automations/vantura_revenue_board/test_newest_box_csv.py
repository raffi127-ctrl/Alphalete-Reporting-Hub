"""The revenue board prices the newest BOX pull by DATE, not by name sort.

    python -m unittest automations.vantura_revenue_board.test_newest_box_csv
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automations.vantura_revenue_board.run import newest_box_csv


class NewestBoxCsvTest(unittest.TestCase):
    def _dir(self, names):
        tmp = Path(tempfile.mkdtemp())
        for n in names:
            (tmp / n).write_text("x")
        return tmp

    def test_a_newer_carlos_pull_beats_an_older_all_pull(self):
        d = self._dir(["box_order_log_all_2026-09-14.csv",
                       "box_order_log_2026-09-16.csv",
                       "box_order_log_2026-09-15.csv"])
        self.assertEqual(newest_box_csv(d).name,
                         "box_order_log_2026-09-16.csv")

    def test_same_day_prefers_carlos_and_ignores_other_names(self):
        d = self._dir(["box_order_log_all_2026-09-16.csv",
                       "box_order_log_2026-09-16.csv",
                       "box_order_log_roshan_2026-09-20.csv"])
        self.assertEqual(newest_box_csv(d).name,
                         "box_order_log_2026-09-16.csv")

    def test_nothing_there(self):
        self.assertIsNone(newest_box_csv(self._dir([])))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
