"""Relay Archive, offline. Fake sheets only -- nothing here calls Google."""
from __future__ import annotations

import datetime as dt
import re
import unittest

from automations.relay_archive import run as R

TODAY = dt.date(2026, 11, 18)
FAULT_HEAD = ["Office", "Day", "Stage", "Summary", "Detail", "Count", "First At",
              "Last At", "Local Time", "Agent", "Platform", "Last Posted At"]
KNOCK_HEAD = ["Office", "Day", "Rows JSON", "Tracker JSON", "Rep Count",
              "Received At", "Local Time", "Last Posted At", "Agent", "Machines"]


def _fault(office, day, detail="Traceback " * 20):
    return [office, day, "crash", "timeout", detail, "3", "", "", "", "a/5", "", ""]


def _knock(office, day, rows='[{"rep": "x"}]'):
    return [office, day, rows, "[]", "4", "", "", "", "a/5", "{}"]


def _col(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


class FakeWS:
    def __init__(self, title, values):
        self.title, self.values = title, [list(r) for r in values]
        self.cleared, self.appended, self.updates = [], [], []
        self.mutate_before_get = None

    def get_all_values(self):
        return [list(r) for r in self.values]

    def row_values(self, n):
        return list(self.values[n - 1]) if n - 1 < len(self.values) else []

    def col_values(self, c):
        return [(r[c - 1] if c - 1 < len(r) else "") for r in self.values]

    def update(self, range_name=None, values=None, value_input_option=None):
        assert range_name == "A1"
        self.values = [list(values[0])] + self.values[1:]

    def append_rows(self, rows, value_input_option=None, insert_data_option=None):
        assert value_input_option == "RAW"
        self.appended.append(rows)
        self.values += [list(r) for r in rows]

    def get(self, rng):
        if self.mutate_before_get:
            self.mutate_before_get(self)
        m = re.match(r"([A-Z]+)1:([A-Z]+)(\d+)$", rng)
        lo, hi, last = _col(m.group(1)), _col(m.group(2)), int(m.group(3))
        return [r[lo:hi + 1] for r in self.values[:last]]

    def batch_clear(self, ranges):
        self.cleared += list(ranges)
        for rng in ranges:
            m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)$", rng)
            c, a, b = _col(m.group(1)), int(m.group(2)), int(m.group(4))
            for n in range(a, b + 1):
                self.values[n - 1][c] = ""

    def batch_update(self, updates, value_input_option=None):
        self.updates += updates
        for u in updates:
            m = re.match(r"([A-Z]+)(\d+)$", u["range"])
            self.values[int(m.group(2)) - 1][_col(m.group(1))] = u["values"][0][0]


class FakeBook:
    def __init__(self, tabs=None):
        self.tabs = dict(tabs or {})

    def worksheet(self, title):
        if title not in self.tabs:
            raise KeyError(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWS(title, [[]])
        return self.tabs[title]


def _faults_book():
    return FakeBook({"ICD Faults": FakeWS("ICD Faults", [
        FAULT_HEAD,
        _fault("kash", "2026-09-15"),          # old -> archived
        _fault("drew", "10/01/2026"),          # old, m/d/Y -> archived
        _fault("cody", "2026-11-11"),          # exactly 7 days -> kept
        _fault("aya", "2026-11-18"),           # today -> kept
        _fault("raf", "not a day"),            # unreadable -> left alone
        _fault("omar", "2026-09-20", ""),      # already emptied -> skipped
        _fault("", "2026-09-01"),              # no office -> skipped
        _fault("tre", "2026-10-02"),           # old -> archived
    ])})


class PlanTest(unittest.TestCase):
    def test_picks_only_old_rows_with_bulk(self):
        p = R.plan_tab(_faults_book().tabs["ICD Faults"].values, "ICD Faults", TODAY)
        self.assertEqual([r["row"] for r in p["rows"]], [2, 3, 9])
        self.assertEqual(p["kept"], 2)
        self.assertEqual(p["unreadable"], 1)
        self.assertEqual(p["cutoff"], dt.date(2026, 11, 11))
        self.assertGreater(p["freed_chars"], 0)

    def test_floor_refuses_a_short_keep(self):
        with self.assertRaises(R.Refused):
            R.plan_tab([FAULT_HEAD], "ICD Faults", TODAY, keep_days=3)
        with self.assertRaises(R.Refused):
            R.plan_tab([KNOCK_HEAD], "ICD Knocks", TODAY, keep_days=8)

    def test_changed_header_refuses(self):
        head = [h if h != "Detail" else "Trace" for h in FAULT_HEAD]
        with self.assertRaises(R.Refused):
            R.plan_tab([head, _fault("kash", "2026-09-15")], "ICD Faults", TODAY)

    def test_columns_found_by_label_not_position(self):
        head = ["Day", "Office"] + KNOCK_HEAD[2:]
        row = ["2026-09-12", "kash"] + _knock("kash", "x")[2:]
        p = R.plan_tab([head, row], "ICD Knocks", TODAY)
        self.assertEqual([r["row"] for r in p["rows"]], [2])

    def test_clear_ranges_merge_consecutive_rows(self):
        plan = {"rows": [{"row": n} for n in (2, 3, 4, 7, 9, 10)],
                "heavy_idx": [2, 3]}
        self.assertEqual(R.clear_ranges(plan),
                         ["C2:C4", "C7:C7", "C9:C10", "D2:D4", "D7:D7", "D9:D10"])

    def test_relay_tab_is_not_configured(self):
        self.assertNotIn("ICD Relay", R.TABS)
        self.assertIn("ICD Relay", R.NEVER)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.src = _faults_book()
        self.arc = FakeBook()

    def _run(self, **kw):
        return R.run_tab(self.src, self.arc, "ICD Faults", TODAY, apply=True,
                         log=lambda *a: None, **kw)

    def test_archives_then_empties_only_old_detail(self):
        before = self.src.tabs["ICD Faults"].get_all_values()
        self._run()
        ws, arc = self.src.tabs["ICD Faults"], self.arc.tabs["ICD Faults"]
        self.assertEqual(len(ws.values), len(before), "no row deleted or added")
        for n in (2, 3, 9):
            self.assertEqual(ws.values[n - 1][4], "", "old detail emptied")
            self.assertEqual(ws.values[n - 1][:4], before[n - 1][:4], "keys kept")
            self.assertEqual(ws.values[n - 1][5:], before[n - 1][5:], "rest kept")
        for n in (4, 5, 6):
            self.assertEqual(ws.values[n - 1], before[n - 1], "recent/unreadable untouched")
        self.assertEqual(arc.values[0], FAULT_HEAD + R.EXTRA_HEAD)
        self.assertEqual([r[:12] for r in arc.values[1:]],
                         [before[1], before[2], before[8]], "whole rows archived")
        self.assertEqual([r[12] for r in arc.values[1:]], ["2", "3", "9"])

    def test_dry_run_writes_nothing(self):
        before = self.src.tabs["ICD Faults"].get_all_values()
        R.run_tab(self.src, self.arc, "ICD Faults", TODAY, apply=False,
                  log=lambda *a: None)
        self.assertEqual(self.src.tabs["ICD Faults"].values, before)
        self.assertEqual(self.arc.tabs, {})

    def test_second_night_after_a_crash_does_not_duplicate(self):
        # Night 1 archived but died before the clear: simulate by archiving,
        # then restoring the source cells.
        before = self.src.tabs["ICD Faults"].get_all_values()
        self._run()
        self.src.tabs["ICD Faults"].values = before
        self._run()
        self.assertEqual(len(self.arc.tabs["ICD Faults"].values), 1 + 3)
        self.assertEqual(self.src.tabs["ICD Faults"].values[1][4], "")

    def test_nothing_emptied_when_a_row_moved(self):
        ws = self.src.tabs["ICD Faults"]

        def insert_row(w):
            w.values.insert(1, _fault("new", "2026-11-18"))
        ws.mutate_before_get = insert_row
        with self.assertRaises(RuntimeError):
            self._run()
        self.assertEqual(ws.cleared, [])

    def test_nothing_emptied_when_the_archive_lost_rows(self):
        class Lossy(FakeWS):
            def append_rows(self, rows, **kw):
                self.appended.append(rows)   # accepted, never stored
        self.arc.tabs["ICD Faults"] = Lossy("ICD Faults", [FAULT_HEAD + R.EXTRA_HEAD])
        with self.assertRaises(RuntimeError):
            self._run()
        self.assertEqual(self.src.tabs["ICD Faults"].cleared, [])

    def test_archive_with_a_different_header_refuses(self):
        self.arc.tabs["ICD Faults"] = FakeWS("ICD Faults", [["Office", "Other"]])
        with self.assertRaises(R.Refused):
            self._run()


class RestoreTest(unittest.TestCase):
    def test_puts_a_day_back_without_overwriting(self):
        src, arc = _faults_book(), FakeBook()
        before = src.tabs["ICD Faults"].get_all_values()
        R.run_tab(src, arc, "ICD Faults", TODAY, apply=True, log=lambda *a: None)
        src.tabs["ICD Faults"].values[2][4] = "live text written since"
        n = R.restore(src, arc, "ICD Faults", dt.date(2026, 9, 15), apply=True,
                      log=lambda *a: None)
        self.assertEqual(n, 1)
        self.assertEqual(src.tabs["ICD Faults"].values[1][4], before[1][4])
        self.assertEqual(src.tabs["ICD Faults"].values[2][4], "live text written since")


class MainGuardsTest(unittest.TestCase):
    def test_relay_tab_refused_by_argparse(self):
        with self.assertRaises(SystemExit):
            R.main(["--tab", "ICD Relay"])

    def test_apply_needs_an_archive(self):
        self.assertEqual(R.main(["--apply", "--archive-id", ""]), 2)

    def test_archive_cannot_be_the_source(self):
        self.assertEqual(R.main(["--apply", "--archive-id", R.SOURCE_ID]), 2)

    def test_a_preview_never_marks_the_hub_card(self):
        from unittest import mock
        from automations.shared import hub_autopublish
        with mock.patch.object(hub_autopublish, "nothing_to_report") as quiet:
            R.main(["--restore", "2026-11-01", "--archive-id", ""])   # refused early
        quiet.assert_called_once()
        with mock.patch.object(hub_autopublish, "nothing_to_report") as quiet:
            R.main(["--apply", "--archive-id", ""])
        quiet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
