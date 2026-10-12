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

    def test_one_ad_several_cities(self):
        # Valeria 10/12: Colten's Assistant Manager ad = Doral + Princeton.
        old = sc.config.SCORECARD_CITIES
        sc.config.SCORECARD_CITIES = {"Entry Level Assistant Manager": "Doral + Princeton, FL"}
        try:
            self.assertEqual(sc.title_city("Entry Level Assistant Manager"),
                             ("Entry Level Assistant Manager", "Doral + Princeton, FL"))
            self.assertEqual(sc.title_city("AT&T Sales Agent – Miami FL"),
                             ("AT&T Sales Agent", "Miami, FL"))
        finally:
            sc.config.SCORECARD_CITIES = old


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


class Replaced(unittest.TestCase):
    """Maddie 10/12: "There were 4 replacements last week"."""

    def setUp(self):
        self.old = sc.config.SCORECARD_REPLACED
        sc.config.SCORECARD_REPLACED = {"2026-10-05": [
            "Entry Level Associate (AT&T)", "AT&T Sales Agent, McKinney, TX"]}

    def tearDown(self):
        sc.config.SCORECARD_REPLACED = self.old

    def test_which_tables(self):
        t = "Entry Level Associate (AT&T) – Arlington TX"
        oct5, oct9 = dt.date(2026, 10, 5), dt.date(2026, 10, 9)
        self.assertTrue(sc.replaced(t, oct5, oct9))                                   # that week
        self.assertTrue(sc.replaced(t, dt.date(2026, 10, 1), dt.date(2026, 10, 16)))  # the month
        self.assertFalse(sc.replaced(t, dt.date(2026, 10, 12), dt.date(2026, 10, 16)))  # next week

    def test_title_with_city(self):
        oct5, oct9 = dt.date(2026, 10, 5), dt.date(2026, 10, 9)
        self.assertTrue(sc.replaced("AT&T Sales Agent – McKinney TX", oct5, oct9))
        self.assertFalse(sc.replaced("AT&T Sales Agent – Arlington TX", oct5, oct9))

    def test_grey_at_the_bottom(self):
        gone = dict(_row("X – Allen TX", 3, 0, {"scheduled": 3, "pending": 0, "showed": 3}),
                    replaced=True)
        low = _row("Y – Plano TX", 3, 0, {"scheduled": 3, "pending": 0, "showed": 0})
        rows = sorted([gone, low], key=sc._rank)
        self.assertEqual(rows[-1], gone)
        self.assertEqual(sc.row_band(gone), sc.REPLACED)
        self.assertEqual(sc.cells(gone, 2)[1], "REPLACED · X")
        self.assertEqual(sc.sheet_row(gone, 2)[1], "REPLACED · X")
        self.assertEqual(sc.count_label(rows), "2 ad titles · 1 replaced")
        self.assertEqual(sc.count_label([low]), "1 ad titles")


if __name__ == "__main__":
    unittest.main()
