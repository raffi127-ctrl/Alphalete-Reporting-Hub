import datetime as dt
import unittest

from automations.rep_knock_breakdown import run as R
from automations.rep_knock_breakdown import streaks as S

OK = "Success, 440 feet is within range of 799 feet."
FAIL = "Failure, 0.45 mile is out of range of 799 feet."


def row(t, gps, addr=""):
    return {"time": t, "gps": gps, "address": addr or t, "status": "No Answer",
            "color": "E3DFDB", "last_note": ""}


class StreakTests(unittest.TestCase):
    def test_minutes_handles_noon_and_midnight(self):
        self.assertEqual(S.minutes("12:05 PM"), 12 * 60 + 5)
        self.assertEqual(S.minutes("12:05 AM"), 5)
        self.assertEqual(S.minutes("06:56 PM"), 18 * 60 + 56)
        self.assertEqual(S.minutes(""), -1)

    def test_in_a_row_means_by_time_not_page_order(self):
        # The page HTML is not in time order. Shuffled, these three failures
        # are not adjacent; by time they are.
        rows = [row("02:30 PM", FAIL), row("06:00 PM", OK), row("02:40 PM", FAIL),
                row("03:00 PM", OK), row("02:35 PM", FAIL)]
        self.assertEqual(S.fail_streaks(rows, 3), [(0, 2)])

    def test_two_fails_is_not_a_streak(self):
        rows = [row("01:00 PM", FAIL), row("01:05 PM", FAIL), row("01:10 PM", OK),
                row("01:15 PM", FAIL)]
        self.assertEqual(S.fail_streaks(rows, 3), [])

    def test_trailing_streak_is_closed(self):
        rows = [row("01:00 PM", OK)] + [row("01:%02d PM" % m, FAIL)
                                         for m in (10, 20, 30, 40)]
        self.assertEqual(S.fail_streaks(rows, 3), [(1, 4)])

    def test_summary(self):
        rows = [row("03:00 PM", FAIL), row("01:00 PM", OK), row("03:05 PM", FAIL)]
        s = S.summary(rows)
        self.assertEqual((s["knocks"], s["gps_fails"], s["first"], s["last"],
                          s["longest_fail_run"]), (3, 2, "01:00 PM", "03:05 PM", 2))

    def test_distance_text(self):
        self.assertEqual(S.distance_text(FAIL), "0.45 mi")
        self.assertEqual(S.distance_text("Failure, 878 feet is out of range of 799 feet."),
                         "878 ft")

    def test_growing_streak_keeps_its_key(self):
        day = dt.date(2026, 10, 13)
        three = [row("01:00 PM", FAIL), row("01:05 PM", FAIL), row("01:10 PM", FAIL)]
        rep = {"pid": "1", "name": "A B", "rows": three}
        k1 = R.streak_texts(rep, day)[0]["key"]
        rep["rows"] = three + [row("01:15 PM", FAIL)]
        k2 = R.streak_texts(rep, day)[0]["key"]
        self.assertEqual(k1, k2)

    def test_text_body(self):
        rep = {"pid": "1", "name": "Diego Del Pozo Borres",
               "rows": [row("08:28 PM", FAIL), row("08:29 PM", FAIL),
                        row("08:30 PM", FAIL)]}
        body = R.streak_texts(rep, dt.date(2026, 10, 13))[0]["body"]
        self.assertIn("Diego Del Pozo Borres has 3 knocks in a row", body)
        self.assertIn("08:28 PM to 08:30 PM", body)

    def test_week_starts_sunday(self):
        self.assertEqual(R.week_sunday(dt.date(2026, 10, 13)), dt.date(2026, 10, 11))
        self.assertEqual(R.week_sunday(dt.date(2026, 10, 11)), dt.date(2026, 10, 11))

    def test_signature_moves_with_new_knocks(self):
        rep = {"rows": [row("01:00 PM", OK)]}
        a = R.signature(rep)
        rep["rows"].append(row("01:30 PM", OK))
        self.assertNotEqual(a, R.signature(rep))


if __name__ == "__main__":
    unittest.main()
