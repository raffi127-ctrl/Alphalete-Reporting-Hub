"""Ad scorecard: the city split and the spreadsheet grid (Raf 10/10)."""
import datetime as dt
import unittest

from automations.ad_photo_threads import scorecard as sc


class SplitCity(unittest.TestCase):
    def test_shapes(self):
        cases = {
            "AT&T Sales Agent – McKinney TX": ("AT&T Sales Agent", "McKinney, TX"),
            "Entry level Sales Manager, Allen, TX": ("Entry level Sales Manager", "Allen, TX"),
            "Wireless Service Associate - Spanish Required – Mesquite TX (Dallas County)":
                ("Wireless Service Associate - Spanish Required", "Mesquite, TX"),
            "Client Solutions Specialist - AT&T Services (Spanish Required), Dallas, TX":
                ("Client Solutions Specialist - AT&T Services (Spanish Required)", "Dallas, TX"),
            "AT&T Customer Representative - Entry Level – Grand Prairie TX":
                ("AT&T Customer Representative - Entry Level", "Grand Prairie, TX"),
            "Marketing Campaigns - Entry Level at Alphalete Marketing · Dallas-Fort Worth Metroplex":
                ("Marketing Campaigns - Entry Level at Alphalete Marketing", "Dallas-Fort Worth"),
            "Event Marketing & Sales Assistant (Spanish Required) – 2 locations":
                ("Event Marketing & Sales Assistant (Spanish Required)", "2 locations"),
            "Some Ad": ("Some Ad", ""),
        }
        for title, want in cases.items():
            self.assertEqual(sc.split_city(title), want, title)


def _row(title, seen, removed, second):
    return {"title": title, "seen": seen, "back": seen - removed, "removed": removed,
            "avg": 3.0, "second": second}


class Grid(unittest.TestCase):
    def test_numbers_and_bands(self):
        good = _row("A – Frisco TX", 4, 1, {"scheduled": 2, "pending": 0, "showed": 2})
        none = _row("B, Allen, TX", 2, 2, None)
        tot = _row("TOTAL", 6, 3, {"scheduled": 2, "pending": 0, "showed": 2})
        day = dt.date(2026, 10, 9)
        rows, kinds = sc.sheet_grid({"day": day, "monday": dt.date(2026, 10, 5),
                                     "first": dt.date(2026, 10, 1), "seconds": [],
                                     "week": [good, none], "week_total": tot,
                                     "month": [good], "month_total": tot}, "Raf")
        ads = [rows[r] for r, k, _ in kinds if k == "ad"]
        self.assertEqual(ads[0][:6], [1, "A", "Frisco, TX", 4, 3, 0.75])
        self.assertEqual(ads[1][:3], [2, "B", "Allen, TX"])
        self.assertEqual(ads[1][9:], ["", "", ""])
        bands = [b for _, k, b in kinds if k == "ad"]
        self.assertEqual(bands[0][4], "70%+")
        self.assertIsNone(bands[1])
        totals = [rows[r] for r, k, _ in kinds if k == "total"]
        self.assertEqual(totals[0][:4], ["", "TOTAL", "", 6])
        self.assertTrue(all(len(r) == len(sc.SHEET_HEAD) for r in rows))


if __name__ == "__main__":
    unittest.main()
