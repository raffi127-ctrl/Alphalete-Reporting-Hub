"""Offline tests for the OwnerVille grid read. No browser, no network.

The stub page returns what the real one returns -- a header list and a list of
cell lists -- so these pin the part that turns a DataTables grid into rows: the
bit that has silently published 2 reps of 22 elsewhere in this repo.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.shared import ownerville_knocks as K


class _Page:
    """The two evaluate() shapes read_rows depends on, and nothing else."""

    def __init__(self, headers, rows):
        self.headers, self.rows = headers, rows

    def wait_for_function(self, *a, **kw):
        return None

    def wait_for_timeout(self, *a, **kw):
        return None

    def evaluate(self, script, *args):
        if "thead" in script:
            return list(self.headers)
        if "_processing" in script:
            return len(self.rows)
        if "tbody tr" in script:
            return [list(r) for r in self.rows]
        return []


class ReadRowsTests(unittest.TestCase):
    HEADERS = ["Rep", "Total Knocks", "No answer", "Sale"]

    def test_rows_are_keyed_by_the_grids_own_headers(self):
        page = _Page(self.HEADERS, [["Ana Griffin", "42", "30", "2"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows, [{"rep": "Ana Griffin", "total knocks": "42",
                                 "no answer": "30", "sale": "2"}])

    def test_blank_rows_are_dropped(self):
        """DataTables renders a 'no data available' row that is not a rep."""
        page = _Page(self.HEADERS, [["", "", "", ""],
                                    ["Ian Rodriguez", "10", "8", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rep"], "Ian Rodriguez")

    def test_an_empty_day_is_rows_not_an_error(self):
        """Nobody has knocked yet is a real answer every single morning."""
        page = _Page(self.HEADERS, [])
        self.assertEqual(K.read_rows(page, log=lambda *_: None), [])

    def test_a_grid_that_never_built_is_an_error_not_an_empty_day(self):
        """No headers means the page is not the grid -- almost always a
        sign-in that did not go through. Reporting it as a quiet day is how an
        office silently stops having a board."""
        page = _Page([], [])
        with self.assertRaises(K.OwnervilleError):
            K.read_rows(page, log=lambda *_: None)

    def test_extra_cells_beyond_the_headers_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1", "2", "3", "surprise"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0]["sale"], "3")

    def test_short_rows_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0], {"rep": "Ana", "total knocks": "1"})

    def test_headers_are_normalised_so_spacing_changes_do_not_break_us(self):
        page = _Page(["Rep", "Total   Knocks "], [["Ana", "5"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertIn("total knocks", rows[0])


class HeaderIndexTests(unittest.TestCase):
    def test_index_maps_normalised_header_to_position(self):
        page = _Page(["Rep", "Total Knocks", "Sale"], [])
        self.assertEqual(K.header_index(page),
                         {"rep": 0, "total knocks": 1, "sale": 2})

    def test_missing_table_yields_an_empty_index(self):
        self.assertEqual(K.header_index(_Page([], [])), {})


if __name__ == "__main__":
    unittest.main()


class CadenceTests(unittest.TestCase):
    """Per-destination cadence: the owners' room every 15 minutes and the rep
    channel once an hour is a normal answer, so 'is this due?' is a question
    about ONE room and its own last post."""

    def setUp(self):
        from automations.icd_alerts import knocks_post as KP
        self.KP = KP
        self.now = dt.datetime(2026, 9, 11, 15, 0)

    def test_never_posted_is_due(self):
        """So an approval takes effect on the next tick, not an hour later."""
        self.assertTrue(self.KP.is_due({"cadence_min": 60}, None, self.now))

    def test_interval_waits_its_full_cadence(self):
        last = self.now - dt.timedelta(minutes=45)
        self.assertFalse(self.KP.is_due({"cadence_min": 60}, last, self.now))
        self.assertTrue(self.KP.is_due({"cadence_min": 30}, last, self.now))

    def test_two_rooms_on_one_office_are_judged_separately(self):
        last_hourly = self.now - dt.timedelta(minutes=20)
        self.assertTrue(self.KP.is_due({"cadence_min": 15}, last_hourly, self.now))
        self.assertFalse(self.KP.is_due({"cadence_min": 60}, last_hourly, self.now))

    def test_fixed_times_fire_just_after_a_slot(self):
        at_slot = dt.datetime(2026, 9, 11, 14, 5)
        self.assertTrue(self.KP.is_due({"cadence_min": 0}, None, at_slot))

    def test_fixed_times_do_not_fire_twice_for_one_slot(self):
        at_slot = dt.datetime(2026, 9, 11, 14, 5)
        already = dt.datetime(2026, 9, 11, 14, 1)
        self.assertFalse(self.KP.is_due({"cadence_min": 0}, already, at_slot))

    def test_fixed_times_are_quiet_between_slots(self):
        between = dt.datetime(2026, 9, 11, 16, 0)
        self.assertFalse(self.KP.is_due({"cadence_min": 0}, None, between))


class FieldHoursTests(unittest.TestCase):
    def setUp(self):
        from automations.icd_alerts import knocks_post as KP
        from automations.icd_alerts import offices as O
        self.KP, self.office = KP, O.get("kash")

    def test_sunday_is_off_for_everyone(self):
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 13, 15, 0)))

    def test_a_weekday_afternoon_is_in(self):
        self.assertTrue(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 11, 15, 0)))

    def test_a_weekday_morning_is_out(self):
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 11, 9, 0)))

    def test_saturday_ends_earlier_than_a_weekday(self):
        self.assertTrue(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 12, 17, 0)))
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 12, 21, 0)))


class ClockTests(unittest.TestCase):
    def test_twelve_hour_clock_without_a_gnu_extension(self):
        from automations.icd_alerts.knocks_post import _clock
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 20, 5)), "8:05 PM")
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 0, 30)), "12:30 AM")
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 12, 0)), "12:00 PM")


class MapTests(unittest.TestCase):
    """The re-key is the part that decides WHICH BOARD gets drawn, because
    knocks_shape() reads the row's KEYS. Flattening every office onto one
    fixed set of fields would draw a plausible-looking board with every
    disposition blank."""

    FIBER = {"id": "101", "rep": "Ana Griffin", "total knocks": "42",
             "no answer": "30", "talk to - not interested": "5",
             "presentation – not interested": "2", "come back": "3",
             "sale": "2", "do not knock": "0", "first knock": "1:35 PM",
             "last knock": "7:42 PM"}
    WIRELESS = {"id": "201", "rep": "Ian", "total knocks": "20",
                "no answer": "10", "not interested": "4", "come back": "2",
                "first knock": "2:00 PM", "last knock": "8:00 PM"}

    def setUp(self):
        from automations.icd_alerts import knocks_map as M
        from automations.total_knocks import pull as TP
        self.M, self.TP = M, TP

    def test_a_fiber_office_reads_as_the_house_board(self):
        self.assertEqual(self.M.shape_of(self.M.to_rows([self.FIBER])), "house")

    def test_a_wireless_office_keeps_its_own_shape(self):
        self.assertEqual(self.M.shape_of(self.M.to_rows([self.WIRELESS])),
                         "wireless")

    def test_total_talk_to_is_calculated_for_the_split(self):
        row = self.M.to_rows([self.FIBER])[0]
        self.assertEqual(row[self.TP.COL_TOTAL_TALK_TO], 12)

    def test_total_talk_to_is_NOT_invented_without_the_split(self):
        """A wireless grid has Come Back and none of the other four. Summing
        'the parts that happen to be here' publishes a number that is wrong in
        the believable direction."""
        row = self.M.to_rows([self.WIRELESS])[0]
        self.assertNotIn(self.TP.COL_TOTAL_TALK_TO, row)

    def test_counts_become_ints_and_times_stay_text(self):
        row = self.M.to_rows([self.FIBER])[0]
        self.assertEqual(row[self.TP.COL_TOTAL_KNOCKS], 42)
        self.assertEqual(row[self.TP.COL_FIRST_KNOCK], "1:35 PM")

    def test_gaps_merge_by_badge_id(self):
        rows = self.M.to_rows(
            [self.FIBER], [{"id": "101", "gaps": "3", "totalGapMinutes": 47}])
        self.assertEqual(rows[0][self.TP.COL_GAPS], 3)
        self.assertEqual(rows[0][self.TP.COL_TOTAL_GAPS], 47)

    def test_a_rep_with_no_tracker_row_keeps_gaps_BLANK_not_zero(self):
        """'Did not clock in' and 'stood still for zero minutes' are different
        facts, and the board draws them differently."""
        rows = self.M.to_rows([self.FIBER], [{"id": "999", "gaps": "1"}])
        self.assertNotIn(self.TP.COL_GAPS, rows[0])

    def test_a_totals_line_is_not_a_person(self):
        rows = self.M.to_rows([self.FIBER, {"rep": "TOTAL", "total knocks": "42"}])
        self.assertEqual(len(rows), 1)

    def test_gaps_phrase_is_parsed_as_a_count(self):
        self.assertEqual(self.M._gaps_count("3 gaps"), 3)
        self.assertEqual(self.M._gaps_count(""), 0)
