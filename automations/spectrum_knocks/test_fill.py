"""python -m unittest automations.spectrum_knocks.test_fill"""
import datetime as dt
import unittest

from automations.spectrum_knocks import fill, pull


class TickDay(unittest.TestCase):
    def at(self, h, m=0):
        return dt.datetime(2026, 11, 18, h, m)

    def test_daytime_refreshes_today(self):
        self.assertEqual(fill.tick_day(self.at(9)), dt.date(2026, 11, 18))
        self.assertEqual(fill.tick_day(self.at(23, 45)), dt.date(2026, 11, 18))

    def test_midnight_hour_closes_yesterday(self):
        self.assertEqual(fill.tick_day(self.at(0, 30)), dt.date(2026, 11, 17))

    def test_night_and_early_morning_do_nothing(self):
        for h in (1, 4, 8):
            self.assertIsNone(fill.tick_day(self.at(h, 59)))


class DateKey(unittest.TestCase):
    def test_text_and_serial_are_the_same_day(self):
        # A cell that lost its date format reads back as a serial; a re-run
        # must still recognise it or the day gets written twice.
        self.assertEqual(fill._date_key("11/17/2026"), dt.date(2026, 11, 17))
        self.assertEqual(fill._date_key("46343"), dt.date(2026, 11, 17))
        self.assertEqual(fill._date_key("junk"), dt.date.min)


class Summarize(unittest.TestCase):
    def test_counts_times_and_breaks(self):
        rows = [
            {"rep": "Dale, Aric", "result": "Not Home", "time": "11/17/2026 12:00 PM"},
            {"rep": "Dale, Aric", "result": "Sold", "time": "11/17/2026 12:05 PM"},
            {"rep": "Dale, Aric", "result": "Unoccupied", "time": "11/17/2026 01:00 PM"},
        ]
        out = pull.summarize(rows, {"1": "Dale, Aric", "2": "Wilson, Hayden"})
        aric = out[0]
        self.assertEqual(aric["Doors"], 3)
        self.assertEqual((aric["Not Home"], aric["Sold"], aric["Other"]), (1, 1, 1))
        self.assertEqual((aric["First Door"], aric["Last Door"]), ("12:00 PM", "1:00 PM"))
        self.assertEqual(aric["Longest Break (min)"], 55)
        self.assertEqual(out[1]["Doors"], 0)

    def test_rows_skip_reps_without_doors(self):
        summary = pull.summarize(
            [{"rep": "A", "result": "Sold", "time": "11/17/2026 12:00 PM"}],
            {"1": "A", "2": "B"})
        rows = fill.build_rows(dt.date(2026, 11, 17), summary, fill.HEADER)
        self.assertEqual([r[1] for r in rows], ["A"])
        self.assertEqual(rows[0][0], "11/17/2026")


if __name__ == "__main__":
    unittest.main()
