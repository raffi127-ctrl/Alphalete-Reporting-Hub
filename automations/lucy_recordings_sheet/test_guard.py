"""python -m unittest automations.lucy_recordings_sheet.test_guard"""
import datetime as dt
import unittest

from automations.lucy_recordings_sheet.run import (
    DUPLICATE, LAYOUTS, NO_OWNER, TAB_OWNER, TOO_SHORT, apply_guard, closed_weeks,
    new_starts_html, new_starts_table, owner_rank_key, table_formula)


def rec(ts, uid="U1", seconds=1800.0, fp=None):
    return {"ts": ts, "uid": uid, "seconds": seconds, "fp": fp, "score": 5.0}


class GuardTest(unittest.TestCase):
    def test_a_real_recording_counts(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", fp="a")])
        self.assertEqual((len(kept), dropped), (1, []))

    def test_same_file_twice_counts_once_and_the_first_one_stays(self):
        first, again = rec("2026-11-01T10:00", fp="a"), rec("2026-11-02T10:00", fp="a")
        kept, dropped = apply_guard([again, first])
        self.assertEqual(kept, [first])
        self.assertEqual(dropped, [(again, DUPLICATE)])

    def test_same_file_from_another_rep_is_still_a_duplicate(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", "U1", 1800.0, "a"),
                                     rec("2026-11-02T10:00", "U2", 1900.0, "a")])
        self.assertEqual((len(kept), dropped[0][1]), (1, DUPLICATE))

    def test_same_rep_same_length_is_a_re_export(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", fp="a", seconds=1800.0),
                                     rec("2026-11-02T10:00", fp="b", seconds=1800.6)])
        self.assertEqual((len(kept), dropped[0][1]), (1, DUPLICATE))

    def test_two_reps_with_the_same_length_both_count(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", "U1", 1800.0, "a"),
                                     rec("2026-11-01T11:00", "U2", 1800.0, "b")])
        self.assertEqual((len(kept), dropped), (2, []))

    def test_too_short_does_not_count(self):
        short = rec("2026-11-01T10:00", seconds=120.0, fp="a")
        kept, dropped = apply_guard([short])
        self.assertEqual((kept, dropped), ([], [(short, TOO_SHORT)]))

    def test_unknown_length_and_fingerprint_still_counts(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", seconds=None),
                                     rec("2026-11-01T11:00", seconds=None)])
        self.assertEqual((len(kept), dropped), (2, []))

    def test_a_short_clip_does_not_block_the_real_one_with_the_same_fingerprint(self):
        kept, dropped = apply_guard([rec("2026-11-01T10:00", seconds=60.0, fp="a"),
                                     rec("2026-11-01T11:00", seconds=1800.0, fp="a")])
        self.assertEqual((len(kept), dropped[0][1]), (1, TOO_SHORT))


class RankTest(unittest.TestCase):
    def test_highest_percent_first_then_recordings_blank_and_no_owner_last(self):
        m = "November 2026"
        rows = [[m, NO_OWNER, 6, "", "", 1.6],
                [m, "Blank", 3, "", "", 5.0],
                [m, "Zero B", 0, 40, 0.0, ""],
                [m, "Colten", 14, 58, 0.24, 4.1],
                [m, "Cyrus", 17, 41, 0.41, 6.7],
                [m, "Eveliz", 11, 23, 0.48, 3.5]]
        self.assertEqual([r[1] for r in sorted(rows, key=owner_rank_key)],
                         ["Eveliz", "Cyrus", "Colten", "Zero B", "Blank", NO_OWNER])

    def test_by_owner_sheet_sorts_on_percent_then_recordings(self):
        self.assertIn("TRUE, 4, FALSE, 2, FALSE)", table_formula(LAYOUTS[TAB_OWNER]))


class NewStartsTest(unittest.TestCase):
    WEEKS = [dt.date(2026, 10, 11), dt.date(2026, 10, 18), dt.date(2026, 10, 25), dt.date(2026, 11, 1)]

    def test_closed_weeks_skip_the_week_in_progress(self):
        self.assertEqual(closed_weeks(dt.date(2026, 11, 9)), self.WEEKS)
        self.assertEqual(closed_weeks(dt.date(2026, 11, 8)), self.WEEKS)

    def test_totals_across_an_owners_offices_only_in_the_closed_weeks(self):
        rows = [["2026-10-11", "2026-10-12", "A1", "x", "10", "5"],
                ["2026-11-01", "2026-11-02", "A2", "x", "10", "3"],
                ["2026-11-08", "2026-11-09", "A1", "x", "99", "99"],
                ["2026-11-01", "2026-11-02", "B1", "y", "4", "4"],
                ["2026-11-01", "2026-11-02", "C1", "z", "0", "0"]]
        owners = [{"id": "a", "name": "Ann"}, {"id": "b", "name": "Bo"}, {"id": "c", "name": "Cy"}]
        offices = {"a": ["A1", "A2"], "b": ["B1"], "c": ["C1"]}
        table, seen = new_starts_table(rows, self.WEEKS, owners, offices)
        self.assertEqual(table, [["Bo", 4, 4, 1.0, 2.0], ["Ann", 20, 8, 0.4, 4.0]])
        self.assertEqual(seen, ["2026-10-11", "2026-11-01"])

    def test_no_data_leaves_the_table_out(self):
        self.assertEqual(new_starts_html([], []), "")

    def test_html_says_the_dates_and_the_total(self):
        html = new_starts_html([["Ann", 20, 8, 0.4, 2.0]], ["2026-10-11", "2026-11-01"])
        self.assertIn("Oct 11 – Nov 7", html)
        self.assertIn("40%", html)
        self.assertIn("Total", html)


if __name__ == "__main__":
    unittest.main()
