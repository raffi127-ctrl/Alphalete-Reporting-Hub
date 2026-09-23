"""Where the BG Status column IS, rather than where it used to be.

September 2026: a "Classroom" column was inserted at F on the D2D OBCL and
every column from there right moved one. The report kept reading K, which was
now Final Status — so it saw "Owner submitted" where it expected a BG status,
decided the whole week needed advancing, and wrote background-check results
into Final Status. These tests are what make that a one-time event.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.bg_check_sync import match

NEW = ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name",
       "Classroom", "Contact Added", "Email", "Phone", "Location",
       "Final Status", "\nBG Status : Last Checked ", "Digi Docs"]
OLD = ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name",
       "Contact Added", "Email", "Phone", "Location", "Final Status",
       "BG Status : Last Checked", "Digi Docs"]


class HeaderTests(unittest.TestCase):

    def test_the_new_layout_resolves_to_L(self):
        cols = match.header_columns(NEW)
        self.assertEqual(match.a1_col(cols["status"]), "L")
        self.assertEqual(match.a1_col(cols["email"]), "H")
        self.assertEqual(match.a1_col(cols["phone"]), "I")

    def test_the_old_layout_still_resolves_to_K(self):
        cols = match.header_columns(OLD)
        self.assertEqual(match.a1_col(cols["status"]), "K")
        self.assertEqual(match.a1_col(cols["email"]), "G")

    def test_final_status_is_never_mistaken_for_bg_status(self):
        for hdr in (NEW, OLD):
            cols = match.header_columns(hdr)
            self.assertNotEqual(cols["status"], cols["final_status"])
            self.assertEqual(hdr[cols["status"] - 1].strip().lower()[:9],
                             "bg status")

    def test_last_name_never_answers_as_the_first_name(self):
        cols = match.header_columns(NEW)
        self.assertEqual(cols["first"], 4)
        self.assertEqual(cols["last"], 5)

    def test_a_header_with_no_bg_column_reports_none(self):
        self.assertNotIn("status", match.header_columns(
            ["#", "Name", "Last Name", "Final Status"]))

    def test_a1_col(self):
        self.assertEqual([match.a1_col(i) for i in (1, 11, 12, 26, 27)],
                         ["A", "K", "L", "Z", "AA"])


class RosterTests(unittest.TestCase):

    ROW = ["1", "Zoria", "1:00", "Jaylen", "Anthony", "", "TRUE",
           "j@x.com", "12145550001", "Arlington", "Owner submitted", "Passed"]

    def test_a_rolling_block_reads_the_shifted_columns(self):
        vals = [["9/21/2026"], NEW, self.ROW]
        people = match.roster_blocks_in_window(
            vals, dt.date(2026, 9, 21), dt.date(2026, 9, 27), "D2D OBCL")
        self.assertEqual(len(people), 1)
        p = people[0]
        self.assertEqual((p.first, p.last), ("Jaylen", "Anthony"))
        self.assertEqual(p.current, "Passed")          # NOT "Owner submitted"
        self.assertEqual(p.email, "j@x.com")
        self.assertEqual(p.phone, "12145550001")

    def test_the_tab_remembers_where_to_write(self):
        vals = [["9/21/2026"], NEW, self.ROW]
        match.roster_blocks_in_window(vals, dt.date(2026, 9, 21),
                                      dt.date(2026, 9, 27), "D2D OBCL")
        self.assertEqual(match.a1_col(match.TAB_COLUMNS["D2D OBCL"]["status"]), "L")

    def test_a_dated_tab_reads_the_shifted_columns(self):
        vals = [["9/21/2026"], NEW, self.ROW]
        people = match.roster_from_dated_tab(vals, "D2D OBCL 9.21")
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].current, "Passed")
        self.assertEqual(match.a1_col(match.TAB_COLUMNS["D2D OBCL 9.21"]["status"]),
                         "L")

    def test_the_old_layout_still_reads_correctly(self):
        old_row = ["1", "Zoria", "1:00", "Jaylen", "Anthony", "TRUE",
                   "j@x.com", "12145550001", "Arlington", "Owner submitted",
                   "Passed"]
        people = match.roster_blocks_in_window(
            [["9/21/2026"], OLD, old_row], dt.date(2026, 9, 21),
            dt.date(2026, 9, 27), "legacy tab")
        self.assertEqual(people[0].current, "Passed")
        self.assertEqual(people[0].email, "j@x.com")


if __name__ == "__main__":
    unittest.main()


class ColumnSanityTests(unittest.TestCase):
    """The alarm that was missing in September: a shifted column still exits 0,
    so the only thing that can catch it is what the column CONTAINS."""

    class _P:
        def __init__(self, current):
            self.current = current

    def _people(self, *values):
        return [self._P(v) for v in values]

    def test_a_healthy_column_says_nothing(self):
        people = self._people("Passed", "Passed", "Sent", "Taken - Pending",
                              "Review", "Unperformable")
        self.assertIsNone(match.column_sanity(people, "week of 9/21/2026"))

    def test_final_status_is_caught_and_named(self):
        people = self._people("Owner submitted", "Terminated", "Owner submitted",
                              "Showed Up To CR", "Needs BlueInk", "MISSING ID")
        why = match.column_sanity(people, "week of 9/21/2026")
        self.assertIsNotNone(why)
        self.assertIn("Final Status column", why)
        self.assertIn("week of 9/21/2026", why)

    def test_a_human_note_is_not_an_alarm(self):
        """Somebody really did type "Pending (Name Issue)" in there."""
        people = self._people("Passed", "Passed", "Pending (Name Issue)",
                              "Sent", "Passed", "Taken - Pending")
        self.assertIsNone(match.column_sanity(people, "w"))

    def test_blanks_are_not_evidence_either_way(self):
        people = self._people("Passed", "", "", "Sent", "", "Review", "")
        self.assertIsNone(match.column_sanity(people, "w"))

    def test_too_few_values_to_judge(self):
        self.assertIsNone(match.column_sanity(
            self._people("Owner submitted", "Terminated"), "w"))

    def test_an_unfamiliar_column_still_trips_without_the_hint(self):
        people = self._people("Dallas", "Arlington", "McKinney", "Coppell",
                              "Frisco", "Irving")
        why = match.column_sanity(people, "w")
        self.assertIsNotNone(why)
        self.assertNotIn("Final Status", why)
