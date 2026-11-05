"""NDS workbook down: Sara fills in, the email says so, nothing becomes a false 0.

Offline: no Sheet, no Tableau.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from automations.org_sales_board import captainship as cap
from automations.org_sales_board import nds_fallback as fb
from automations.org_sales_board import tabs

D2, D3, D4 = dt.date(2026, 11, 2), dt.date(2026, 11, 3), dt.date(2026, 11, 4)
RUN = dt.date(2026, 11, 5)
PARSED = {"colten wright": {"Wireless Lines": {D3: 25}, "AIA": {D3: 2},
                            "Internet": {D3: 1}, "Something Else": {D3: 99}}}
EMPTY = RuntimeError("Couldn't find the 'X' sheet in the Crosstab dialog — "
                     "saw 0 thumb(s): []. The view may have changed.")


class Shapes(unittest.TestCase):
    def test_captainship_total_is_wireless_plus_aia_plus_internet(self):
        self.assertEqual(fb.program_shape(PARSED),
                         {"colten wright": {"Total": {D3: 28}}})

    def test_section_is_wireless_lines_only(self):
        self.assertEqual(fb.section_shape(PARSED),
                         {"colten wright": {"Wireless": {D3: 25}}})

    def test_owner_with_no_counted_measure_is_absent(self):
        self.assertEqual(fb.program_shape({"x": {"Other": {D3: 5}}}), {})


class Note(unittest.TestCase):
    def test_note_appears_then_goes_when_the_workbook_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / fb.NOTE_FILE
            with mock.patch.object(fb, "_note_path", return_value=path):
                self.assertIsNone(fb.note_for(RUN))
                fb.mark_used(RUN)
                self.assertEqual(fb.note_for(RUN), fb.NOTE_TEXT)
                fb.clear(RUN)
                self.assertIsNone(fb.note_for(RUN))


class ProgramFallback(unittest.TestCase):
    def run_pull(self, sara):
        calls = []

        def pull_section(spec, out_dir, page, logfn=None, today=None):
            calls.append(spec.section_label)
            if spec.section_label == "PROG_nds":
                raise EMPTY
            return "ignored.csv"

        with mock.patch("automations.org_sales_board.section_pull.pull_section_byday",
                        pull_section), \
                mock.patch("automations.org_sales_board.section_pull.parse_byday",
                           return_value={}), \
                mock.patch.object(fb, "pull", sara), \
                mock.patch.object(fb, "mark_used") as marked:
            prog, failed = cap.pull_programs(None, RUN, programs=["nds"],
                                             logfn=lambda m: None)
        return prog, failed, calls, marked

    def test_empty_workbook_goes_to_sara_at_once(self):
        prog, failed, calls, marked = self.run_pull(lambda *a, **k: PARSED)
        self.assertEqual(calls, ["PROG_nds"])          # no 3 slow attempts
        self.assertEqual(failed, [])
        self.assertEqual(prog["nds"], {"colten wright": {"Total": {D3: 28}}})
        marked.assert_called_once_with(RUN)

    def test_sara_failing_too_is_a_failed_program_without_a_note(self):
        def boom(*a, **k):
            raise RuntimeError("no")
        prog, failed, _calls, marked = self.run_pull(boom)
        self.assertEqual(failed, ["nds"])
        self.assertEqual(prog["nds"], {})
        marked.assert_not_called()


class FakeWs:
    title = tabs.BOARD_TAB

    def __init__(self):
        self.updates = []

    def batch_update(self, updates, value_input_option=None):
        self.updates = updates


def anchor():
    return types.SimpleNamespace(
        day_cols=[3, 4, 5, 6, 7, 8, 9], running_col=10, week_total_col=3,
        daily=[(10, "Found Rep"), (11, "Unfound Rep")], leaderboard=[])


class KeepUnfound(unittest.TestCase):
    def fill(self, keep):
        ws = FakeWs()

        def per(name, metric=None):
            return {D2: 5} if name == "Found Rep" else {}

        missing = cap.fill_captainship(ws, anchor(), D4, per, dry_run=False,
                                       keep_unfound=keep)
        return ws.updates, missing

    def test_unfound_row_is_not_touched_when_a_program_is_missing(self):
        updates, missing = self.fill(True)
        ranges = [u["range"] for u in updates]
        self.assertTrue(any("10" in r for r in ranges))
        self.assertFalse(any("11" in r for r in ranges))
        self.assertEqual(missing, [])

    def test_unfound_row_is_still_zero_on_a_complete_run(self):
        updates, missing = self.fill(False)
        self.assertEqual(missing, ["Unfound Rep"])
        row = [u for u in updates if u["range"].endswith("11") and ":" in u["range"]][0]
        self.assertEqual(row["values"][0][:2], [0, 0])


if __name__ == "__main__":
    unittest.main()
