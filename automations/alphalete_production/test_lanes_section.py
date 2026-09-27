import datetime as dt
import unittest

from automations.alphalete_production import capture as C
from automations.alphalete_production import pages as P


class LanesSectionTest(unittest.TestCase):
    def test_range_covers_filled_area_only(self):
        grid = [["Current Week", "", "", "", "", "", "Last week"],
                ["Super", "", "", "", "", "", "Super", "", "", "", "", "", "2wks"],
                ["Ana", "", "", "", "", "", "Bo"],
                ["", "", "", "", "", "", ""]]
        self.assertEqual(C.lanes_range(grid), "A1:M3")

    def test_posts_every_day_last(self):
        for d in range(7):
            ids = [s["id"] for s in P.sections_for(dt.date(2026, 9, 28) + dt.timedelta(d))]
            self.assertEqual(ids[-1], "lanes")


if __name__ == "__main__":
    unittest.main()
