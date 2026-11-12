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
        self.assertEqual(table, [["Bo (1 wk)", 4, 4, 1.0, 4.0], ["Ann", 20, 8, 0.4, 4.0]])
        self.assertEqual(seen, ["2026-10-11", "2026-11-01"])

    def test_no_data_leaves_the_table_out(self):
        self.assertEqual(new_starts_html([], []), "")

    def test_html_says_the_dates_and_the_total(self):
        html = new_starts_html([["Ann", 20, 8, 0.4, 2.0]], ["2026-10-11", "2026-11-01"])
        self.assertIn("Oct 11 – Nov 7", html)
        self.assertIn("40%", html)
        self.assertIn("Total", html)

    def test_first_table_gets_the_new_start_column(self):
        from automations.lucy_recordings_sheet.run import build_email_html, ns_pct_by_owner
        ns = ns_pct_by_owner([["Ann (1 wk)", 10, 6, 0.6, 6.0], ["Bo", 10, 2, 0.2, 0.5]])
        self.assertEqual(ns, {"Ann": 0.6, "Bo": 0.2, "": 0.4})
        html = build_email_html("Nov", [["Nov", 5, 50, 0.1, 4.0, 0]],
                                [["Nov", "Ann", 3, 10, 0.3, 7.0]], "x", False, ns)
        self.assertIn("New Start % (4 wk)", html)
        self.assertIn(">60%<", html)
        self.assertIn(">40%<", html)

    def test_first_table_gets_the_new_starts_count(self):
        from automations.lucy_recordings_sheet.run import build_email_html, ns_count_by_owner
        nc = ns_count_by_owner([["Ann (1 wk)", 10, 6, 0.6, 6.0], ["Bo", 10, 2, 0.2, 0.5]])
        self.assertEqual(nc, {"Ann": 6, "Bo": 2, "": 8})
        html = build_email_html("Nov", [["Nov", 5, 50, 0.1, 4.0, 0]],
                                [["Nov", "Ann", 3, 10, 0.3, 7.0], ["Nov", "Cy", 1, 5, 0.2, 5.0]],
                                "x", False, {"Ann": 0.6}, nc)
        self.assertIn("New Starts (4 wk)", html)
        self.assertIn('font-weight:bold">6</td></tr>', html)
        self.assertIn('font-weight:bold">—</td></tr>', html)
        self.assertIn(">8<", html)


if __name__ == "__main__":
    unittest.main()


class YesterdayTest(unittest.TestCase):
    def test_lists_counted_and_not_counted_for_that_day_only(self):
        from automations.lucy_recordings_sheet.run import COUNTED, yesterday_rows
        export = {"owners": [{"id": "o1", "name": "JD Mascorro"}],
                  "reps": {"U1": {"owner_id": "o1"}},
                  "names": {"U1": "Ana Lopez", "U2": "Bo Ray"}}
        a = rec("2026-11-10T09:05:00", "U1", 1800.0, "a")
        b = rec("2026-11-10T14:30:00", "U1", 1800.0, "a")
        c = rec("2026-11-11T08:00:00", "U2", 1500.0, "c")
        kept, dropped = apply_guard([a, b, c])
        rows = yesterday_rows(kept, dropped, export, {"U2": ("Kash Rai", "knocks")}, "2026-11-10")
        self.assertEqual([r[0] for r in rows], ["9:05 AM", "2:30 PM"])
        self.assertEqual(rows[0][1:5], ["Ana Lopez", "JD Mascorro", 30, 5.0])
        self.assertEqual(rows[0][5], COUNTED)
        self.assertEqual(rows[1][5], "Not counted: " + DUPLICATE)

    def test_empty_day_still_says_so(self):
        from automations.lucy_recordings_sheet.run import yesterday_text
        self.assertIn("No recordings", yesterday_text("2026-11-10", []))

    def test_text_groups_by_owner_and_marks_not_counted(self):
        from automations.lucy_recordings_sheet.run import COUNTED, yesterday_text
        txt = yesterday_text("2026-11-10", [
            ["9:05 AM", "Ana Lopez", "JD Mascorro", 30, 5.0, COUNTED],
            ["2:30 PM", "Ana Lopez", "JD Mascorro", 30, 5.0, "Not counted: " + DUPLICATE]])
        self.assertIn("*JD Mascorro* (1)", txt)
        self.assertIn(":x: " + DUPLICATE, txt)
        self.assertIn("*1 counted*", txt)
        self.assertIn("1. Ana L. · 9:05 AM · score 5.0 :white_check_mark:", txt)
        self.assertIn("2. Ana L. · 2:30 PM", txt)
        self.assertNotIn(" min ·", txt)


class ScopeTest(unittest.TestCase):
    def test_raf_office_plus_no_owner(self):
        from automations.lucy_recordings_sheet.run import in_yesterday_scope
        self.assertTrue(in_yesterday_scope("Rafael Hidalgo"))
        self.assertFalse(in_yesterday_scope("Algemar Kennel"))
        self.assertTrue(in_yesterday_scope(NO_OWNER))
        self.assertFalse(in_yesterday_scope("Carlos Hidalgo"))
        self.assertFalse(in_yesterday_scope("Kash Rai"))


class ShortNameTest(unittest.TestCase):
    def test_first_name_plus_last_initial(self):
        from automations.lucy_recordings_sheet.run import NO_NAME, short_name, yesterday_text, COUNTED
        self.assertEqual(short_name("Hank Tran"), "Hank T.")
        self.assertEqual(short_name("savannah moreno"), "Savannah M.")
        self.assertEqual(short_name("ANDRES MEJIA"), "Andres M.")
        self.assertEqual(short_name("Sydney"), "Sydney")
        self.assertEqual(short_name(NO_NAME), NO_NAME)
        txt = yesterday_text("2026-11-10", [["9:05 AM", "Hank Tran", "Rafael Hidalgo", 30, 9.0, COUNTED]])
        self.assertIn("1. Hank T. · 9:05 AM", txt)
        self.assertNotIn("Tran", txt)


class AskOwnerTest(unittest.TestCase):
    def test_only_reps_with_no_owner_and_no_guess(self):
        from automations.lucy_recordings_sheet.run import no_owner_reps, ask_owner_text
        export = {"owners": [{"id": "o1", "name": "Rafael Hidalgo"}],
                  "reps": {"U1": {"owner_id": "o1"}},
                  "names": {"U1": "Hank Tran", "U2": "kingdavid mensah", "U3": "Bo Ray"}}
        recs = [rec("2026-11-11T09:00:00", "U1", 1800.0, "a"),
                rec("2026-11-11T10:09:00", "U2", 1800.0, "b"),
                rec("2026-11-11T10:20:00", "U2", 1800.0, "b"),
                rec("2026-11-11T11:00:00", "U3", 1800.0, "c"),
                rec("2026-11-10T11:00:00", "U2", 1800.0, "d")]
        kept, dropped = apply_guard(recs)
        got = no_owner_reps(kept, dropped, export, {"U3": ("Kash Rai", "knocks")}, "2026-11-11")
        self.assertEqual(got, [("U2", "kingdavid mensah", "10:09 AM")])
        txt = ask_owner_text("kingdavid mensah", "2026-11-11", "10:09 AM")
        self.assertIn("Hi Kingdavid!", txt)
        self.assertIn("Wednesday, Nov 11 at 10:09 AM", txt)
        self.assertIn("Who is your owner?", txt)
