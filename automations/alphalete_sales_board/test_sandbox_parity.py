"""sandbox_parity -- the walk-through of the live tab against its SANDBOX twin.

No Sheet, no network: two small grids shaped like the board (row 1 day banners
+ per-rep column titles, row 3 sub-headers with the '#' rank column, a TOTALS
row, the 'New Starts/Raf' box) and the comparison run over them.

    python -m unittest automations.alphalete_sales_board.test_sandbox_parity
"""
from __future__ import annotations

import copy
import datetime as dt
import unittest

from automations.alphalete_sales_board import sandbox_parity as SP

MONDAY = dt.date(2026, 9, 7)
LIVE = "Sales Board WE 9.13"
SBX = "SANDBOX — Sales Board WE 9.13"

DAYS = ("MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN")
SUBS = ("Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call")
FIRST_DAY_COL = 4                   # A=blank, B='#', C=names, D.. day blocks


def _board(names, *, trio_on=()):
    """A grid with the given rep names. `trio_on` widens those days with the
    three Talk-To columns after TK, the way the sandbox is built."""
    cols = []                       # (day, sub) per column, left to right
    for d in DAYS:
        subs = list(SUBS)
        if d in trio_on:
            i = subs.index("TK") + 1
            subs[i:i] = list(SP.TRIO)
        cols += [(d, s) for s in subs]
    tail = ["Termination Date", "# Days Worked", "Start Date"]
    width = FIRST_DAY_COL - 1 + len(cols) + len(tail)

    def blank():
        return [""] * width

    r1, r2, r3 = blank(), blank(), blank()
    seen = set()
    for i, (d, s) in enumerate(cols):
        c = FIRST_DAY_COL + i
        if d not in seen:
            r1[c - 1] = d
            seen.add(d)
        r3[c - 1] = s
    for j, t in enumerate(tail):
        r1[FIRST_DAY_COL - 1 + len(cols) + j] = t
    r3[1] = "#"
    r3[2] = "WE 9/7- 9/13"
    grid = [r1, r2, r3]
    for k, n in enumerate(names, 1):
        row = blank()
        row[1], row[2] = str(k), n
        grid.append(row)
    tot = blank()
    tot[2] = "TOTALS"
    grid.append(tot)
    grid.append(blank())
    lab = blank()
    lab[2] = "New Starts/Raf"
    grid.append(lab)
    hdr = blank()
    for i, d in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday",
                           "Friday", "Saturday")):
        hdr[4 + i] = d
    hdr[2] = "Classroom"
    grid.append(hdr)
    sub = blank()
    sub[4] = "Roll Call"            # the box's own sub-header, like the board
    grid.append(sub)
    grid.append(blank())
    return grid


def _col(grid, day, sub):
    for c in range(1, len(grid[0]) + 1):
        if grid[0][c - 1] == day:
            for cc in range(c, len(grid[0]) + 1):
                if grid[2][cc - 1] == sub:
                    return cc
    raise KeyError((day, sub))


def _row(grid, name):
    for r, line in enumerate(grid, 1):
        if len(line) > 2 and line[2] == name:
            return r
    raise KeyError(name)


def _set(grid, name, day, sub, value):
    grid[_row(grid, name) - 1][_col(grid, day, sub) - 1] = value


NAMES = ["Ana Diaz", "Bo Ortiz", "Cy Lopez", "Di Reyes", "Ed Park",
         "Fe Cruz"]


def _pair():
    """The live tab and its twin: same people, twin sorted in reverse (the two
    tabs never share row numbers), twin carries the trio on THU."""
    return _board(NAMES), _board(list(reversed(NAMES)), trio_on=("THU",))


class TabNames(unittest.TestCase):
    def test_live_title_strips_the_real_prefix(self):
        self.assertEqual(SP.live_title(SBX), LIVE)

    def test_week_monday_is_sunday_minus_six(self):
        self.assertEqual(SP.week_monday(LIVE, dt.date(2026, 9, 11)), MONDAY)
        self.assertEqual(SP.week_monday(SBX, dt.date(2026, 9, 11)), MONDAY)
        self.assertIsNone(SP.week_monday("Line Up"))


class Terminations(unittest.TestCase):
    """Eve's ask: the T marks are typed by hand, so the walk-through LISTS the
    ones the two tabs disagree about and never writes them."""

    def test_identical_tabs_have_nothing_to_load(self):
        live, sbx = _pair()
        _set(live, "Bo Ortiz", "WED", "Roll Call", "T")
        _set(sbx, "Bo Ortiz", "WED", "Roll Call", "T")
        only_l, only_s, both, _n = SP.term_diffs(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual((only_l, only_s, both), ([], [], []))

    def test_t_on_live_only_is_a_step_for_the_sandbox(self):
        live, sbx = _pair()
        _set(live, "Bo Ortiz", "WED", "Roll Call", "T")
        only_l, only_s, both, _n = SP.term_diffs(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual([t.name for t in only_l], ["Bo Ortiz"])
        self.assertEqual(only_l[0].term_date, dt.date(2026, 9, 9))
        self.assertEqual((only_s, both), ([], []))

    def test_t_on_sandbox_only_is_a_step_for_the_live_tab(self):
        live, sbx = _pair()
        _set(sbx, "Cy Lopez", "FRI", "Apps", "T")   # a T outside Roll Call counts
        only_l, only_s, _b, _n = SP.term_diffs(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual([t.name for t in only_s], ["Cy Lopez"])
        self.assertEqual(only_l, [])

    def test_same_rep_different_day_is_flagged(self):
        live, sbx = _pair()
        _set(live, "Di Reyes", "TUES", "Roll Call", "T")
        _set(sbx, "Di Reyes", "THU", "Roll Call", "T")
        _l, _s, both, _n = SP.term_diffs(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual(len(both), 1)
        self.assertEqual((both[0][0].term_date, both[0][1].term_date),
                         (dt.date(2026, 9, 8), dt.date(2026, 9, 10)))

    def test_summary_names_the_pending_termination(self):
        live, sbx = _pair()
        _set(live, "Bo Ortiz", "WED", "Roll Call", "T")
        lines = SP.summary_lines(live, LIVE, sbx, SBX, MONDAY)
        self.assertIn("bajas live 1 / sandbox 0", lines[0])
        self.assertTrue(any("PASO MANUAL" in ln and "Bo Ortiz" in ln
                            and "NO en la sandbox" in ln for ln in lines))

    def test_report_always_shows_the_termination_step(self):
        """Even with nothing pending, the step is printed -- it is a check she
        ticks, not an alarm that only exists when something is wrong."""
        live, sbx = _pair()
        lines, pend = SP.report(live, LIVE, sbx, SBX, MONDAY)
        text = "\n".join(lines)
        self.assertIn("PASO MANUAL - BAJAS", text)
        self.assertIn("ok: las dos tabs marcan las mismas 0 baja(s)", text)
        self.assertEqual(pend, 0)

    def test_nothing_is_written(self):
        live, sbx = _pair()
        _set(live, "Bo Ortiz", "WED", "Roll Call", "T")
        before = (copy.deepcopy(live), copy.deepcopy(sbx))
        SP.report(live, LIVE, sbx, SBX, MONDAY)
        SP.summary_lines(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual((live, sbx), before)

    def test_knocks_on_the_t_day_then_nothing_is_an_afternoon_termination(self):
        """Ivan Munoz, WE 9.13: T on Monday with TK=22, T every day after.
        He knocked in the morning and was let go in the afternoon -- a baja,
        not a 'revisar'."""
        live, sbx = _pair()
        for g in (live, sbx):
            _set(g, "Bo Ortiz", "MON", "TK", "22")
            for d in DAYS:
                _set(g, "Bo Ortiz", d, "Roll Call", "T")
        terms, notes = SP.terminations(live, LIVE, MONDAY)
        self.assertEqual(notes, [])
        self.assertEqual(terms["bo ortiz"].term_date, MONDAY)
        self.assertEqual(SP.term_diffs(live, LIVE, sbx, SBX, MONDAY),
                         ([], [], [], []))

    def test_afternoon_termination_missing_on_sandbox_is_a_step(self):
        live, sbx = _pair()
        _set(live, "Bo Ortiz", "MON", "TK", "22")
        _set(live, "Bo Ortiz", "MON", "Roll Call", "T")
        _set(live, "Bo Ortiz", "TUES", "Roll Call", "T")
        only_l, _s, _b, notes = SP.term_diffs(live, LIVE, sbx, SBX, MONDAY)
        self.assertEqual([t.name for t in only_l], ["Bo Ortiz"])
        self.assertEqual(notes, [])

    def test_still_working_after_the_t_is_a_revisar(self):
        live, sbx = _pair()
        _set(live, "Cy Lopez", "MON", "Roll Call", "T")
        _set(live, "Cy Lopez", "MON", "Int", "1")
        _set(live, "Cy Lopez", "WED", "Int", "2")
        terms, notes = SP.terminations(live, LIVE, MONDAY)
        self.assertNotIn("cy lopez", terms)
        self.assertEqual(len(notes), 1)
        self.assertIn("sigue trabajando", notes[0])
        self.assertIn("mie Int=2", notes[0])

    def test_off_after_the_t_is_not_work(self):
        live, _sbx = _pair()
        _set(live, "Ed Park", "MON", "Roll Call", "T")
        _set(live, "Ed Park", "MON", "TK", "5")
        _set(live, "Ed Park", "TUES", "Roll Call", "Off")
        terms, notes = SP.terminations(live, LIVE, MONDAY)
        self.assertIn("ed park", terms)
        self.assertEqual(notes, [])


class Cells(unittest.TestCase):
    def test_rows_are_matched_by_name_not_position(self):
        live, sbx = _pair()
        _set(live, "Ana Diaz", "MON", "Int", "2")
        _set(sbx, "Ana Diaz", "MON", "Int", "2")
        diffs, _info = SP.cell_diffs(live, sbx)
        self.assertEqual(diffs, [])

    def test_sales_gap_is_automatic_roll_call_gap_is_manual(self):
        live, sbx = _pair()
        _set(live, "Ana Diaz", "MON", "Int", "2")
        _set(live, "Ed Park", "TUES", "Roll Call", "Here")
        diffs, _info = SP.cell_diffs(live, sbx)
        kinds = {(d[2], d[3]): d[0] for d in diffs}
        self.assertEqual(kinds[("Int", "Ana Diaz")], SP.AUTO)
        self.assertEqual(kinds[("Roll Call", "Ed Park")], SP.MANO)

    def test_status_letter_in_a_sales_cell_is_manual(self):
        live, sbx = _pair()
        _set(live, "Fe Cruz", "WED", "Int", "X")
        diffs, _info = SP.cell_diffs(live, sbx)
        self.assertEqual([d[0] for d in diffs], [SP.MANO])

    def test_apps_is_skipped_and_trio_is_info(self):
        live, sbx = _pair()
        _set(live, "Ana Diaz", "MON", "Apps", "3")
        diffs, info = SP.cell_diffs(live, sbx)
        self.assertEqual(diffs, [])
        self.assertTrue(any("THU" in i and "el trio, esperado" in i
                            for i in info), info)

    def test_wk_tag_is_not_a_roster_difference(self):
        live = _board(["Jaylen Walker"])
        sbx = _board(["Jaylen Walker (Wk 2)"])
        self.assertEqual(set(SP.roster(live)), set(SP.roster(sbx)))


class Patched(unittest.TestCase):
    """The sweep compares grids read before it wrote; patching them with the
    batch it just sent keeps a cell it is fixing from reading as a gap."""

    def test_patch_applies_single_cell_updates_on_a_copy(self):
        live, sbx = _pair()
        col = _col(sbx, "MON", "Int")
        row = _row(sbx, "Ana Diaz")
        letters = ""
        n = col
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        _set(live, "Ana Diaz", "MON", "Int", "2")
        out = SP.patched(sbx, [{"range": "%s%d" % (letters, row),
                                "values": [["2"]]}])
        self.assertEqual(out[row - 1][col - 1], "2")
        self.assertEqual(sbx[row - 1][col - 1], "")     # original untouched
        self.assertEqual(SP.cell_diffs(live, out)[0], [])


if __name__ == "__main__":
    unittest.main()
