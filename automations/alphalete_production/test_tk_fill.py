"""The TK fill's three promises, pinned without a browser or a Sheet.

Run:  PYTHONPATH=. python -m unittest \
          automations.alphalete_production.test_tk_fill

WHAT THIS GUARDS. The fill runs unattended every 15 minutes against a live
board people are typing into, so the three rules that keep it safe are the
three worth a test:

  1. THE COLUMN IS FOUND BY LABEL. 'TK' replaced 'EN' on the WE 9.6 tab and
     the day blocks move every week, so a hardcoded index is a time bomb. A
     tab whose day block has NO TK column must return None (stop), never a
     neighbouring column (silently write knocks into DTV).
  2. IT ONLY EVER RAISES. A pull that comes back short mid-day must not lower
     a number that is already on the board.
  3. IT NEVER OVERWRITES A HUMAN. A TK cell holding 'X' or 'T' is somebody's
     mark; it is reported, not replaced.

The grid fixture mirrors the real tab's three header rows (day labels in row
1, sub-headers in row 3, reps from row 4 to TOTALS) — including the second
numbered section, because the '#' counter restarting is exactly what a roster
that filters too early would miss.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.alphalete_production import tk_fill as T

# Row 1: day labels sit over the first column of each block.
# Row 3: '#' anchors the name column; each day block ends Apps..Roll Call.
_DAY_BLOCK = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]


def _grid(*, tk_label: str = "TK", extra_rows=(), talk_to=False):
    head = ["", "", ""] + ["APPS", "INT", "INT UP", "DTV", "NL", "TK", "Cx"]
    row1 = list(head)
    row3 = ["", "#", "WE 8/31- 9/6", "APPS", "INT", "INT UP", "DTV", "NL",
            "TK", "Cx"]
    block = _DAY_BLOCK if not talk_to else (
        _DAY_BLOCK[:6] + ["Total Talk-To's", "% of TT's per knock",
                          "AVG app per TT"] + _DAY_BLOCK[6:])
    for label in ("MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"):
        row1 += [label] + [""] * (len(block) - 1)
        row3 += [b if b != "TK" else tk_label for b in block]
    row2 = [""] * len(row1)

    rows = [row1, row2, row3]

    # Monday's knock cell, located the way the fixture knows it and NOT via
    # tk_col — the EN variant below exists precisely to make tk_col say None.
    mon_tk = row1.index("MON") + block.index("TK")

    def rep(num, name, tk=""):
        r = [""] * len(row1)
        r[1], r[2] = str(num), name
        r[mon_tk] = tk
        return r

    # first numbered section
    rows.append(rep(1, "Zoria Johnson"))
    rows.append(rep(2, "Noemi (Ivette) Ontiveros", "12"))
    rows.append(rep(3, "Anthony Coca", "X"))
    rows.append([""] * len(row1))                 # the blank band between them
    # second section — the '#' counter restarts here
    rows.append(rep(1, "Raphael Luzes "))
    rows.append(rep(2, "Ivan Soto"))
    for r in extra_rows:
        rows.append(r)
    totals = [""] * len(row1)
    totals[2] = "TOTALS"
    rows.append(totals)
    return rows


MONDAY = dt.date(2026, 8, 31)     # the WE 9.6 tab's Monday
FRIDAY = dt.date(2026, 9, 4)


class ColumnIsFoundByLabel(unittest.TestCase):
    def test_each_weekday_gets_its_own_block(self):
        g = _grid()
        cols = {d: T.tk_col(g, MONDAY + dt.timedelta(days=d)) for d in range(7)}
        self.assertEqual(len(set(cols.values())), 7, cols)
        # the blocks are 8 wide, so consecutive days are 8 apart
        self.assertEqual(cols[1] - cols[0], len(_DAY_BLOCK))

    def test_a_tab_still_labelled_EN_returns_None(self):
        """The old sub-header. Returning a neighbour here would write knocks
        into somebody's DTV column, which is why this stops instead."""
        self.assertIsNone(T.tk_col(_grid(tk_label="EN"), MONDAY))

    def test_friday_is_not_mondays_column(self):
        g = _grid()
        self.assertNotEqual(T.tk_col(g, FRIDAY), T.tk_col(g, MONDAY))


class TalkToColumn(unittest.TestCase):
    """Eve's three Talk-To columns widen the day block from 8 to 11. The fill
    has to find the new one on a tab that has it and say None on one that does
    not — the two shapes live side by side while the change rolls out."""

    def test_it_sits_right_after_TK_on_a_widened_tab(self):
        g = _grid(talk_to=True)
        for day in (MONDAY, FRIDAY):
            self.assertEqual(T.tt_col(g, day), T.tk_col(g, day) + 1)

    def test_an_old_eight_column_tab_has_none(self):
        self.assertIsNone(T.tt_col(_grid(), MONDAY))

    def test_it_never_reads_into_the_next_day(self):
        """Only THU carries the columns. Every other day must come back None
        rather than reaching across the block boundary into THU's."""
        g = _grid(talk_to=True)
        row3 = g[T.SUB_ROW - 1]
        for day in (MONDAY, FRIDAY):
            lo = T.tk_col(g, day)
            for off in range(1, 4):                   # blank out that day's trio
                row3[lo + off - 1] = ""
            self.assertIsNone(T.tt_col(g, day))

    def test_each_weekday_gets_its_own(self):
        g = _grid(talk_to=True)
        cols = {d: T.tt_col(g, MONDAY + dt.timedelta(days=d)) for d in range(7)}
        self.assertEqual(len(set(cols.values())), 7, cols)


class OwnervilleStatusTag(unittest.TestCase):
    """Ownerville hangs 'RT' off the end of some names. Eve 2026-09-08: those
    reps' knocks belong on the board, so the tag must not cost them the match."""

    def _rows(self):
        return {4: "Edgar Camunez (Wk 2)",
                5: "Ibukunoluwa Olapade Ogunlola (Wk 2)",
                6: "Justin Avila"}

    def test_a_trailing_RT_still_finds_the_rep(self):
        m, un, amb = T.match_rows({"Edgar Camunez RT": 66}, self._rows())
        self.assertEqual(m, {4: 66})
        self.assertEqual((un, amb), ([], []))

    def test_it_works_with_the_middle_name_fallback_too(self):
        m, un, _a = T.match_rows({"Ibukunoluwa Olapade Ogunlola RT": 165},
                                 self._rows())
        self.assertEqual(m, {5: 165})
        self.assertEqual(un, [])

    def test_an_untagged_name_is_unchanged(self):
        m, _u, _a = T.match_rows({"Justin Carlos Avila": 40}, self._rows())
        self.assertEqual(m, {6: 40})

    def test_a_two_word_name_keeps_its_last_word(self):
        """Never strip a name down to one word — 'RT' as somebody's real
        surname is a worse thing to get wrong than a tag left on."""
        self.assertEqual(T._ov_norm("Edgar RT"), "edgar rt")
        self.assertEqual(T._ov_norm("Edgar Camunez RT"), "edgar camunez")


class RosterCoversBothSections(unittest.TestCase):
    def test_the_second_numbered_section_is_included(self):
        rows = T.roster(_grid())
        self.assertIn("Raphael Luzes", [n.strip() for n in rows.values()])
        self.assertEqual(len(rows), 5)

    def test_totals_and_everything_under_it_are_out(self):
        self.assertNotIn("TOTALS", T.roster(_grid()).values())


class Matching(unittest.TestCase):
    def test_a_parenthesised_nickname_still_matches(self):
        rows = T.roster(_grid())
        m, un, amb = T.match_rows({"Noemi Ontiveros": 26}, rows)
        self.assertEqual(list(m.values()), [26])
        self.assertEqual((un, amb), ([], []))

    def test_a_rep_with_no_row_is_reported_not_guessed(self):
        m, un, amb = T.match_rows({"Algemar Kennel": 14}, T.roster(_grid()))
        self.assertEqual(m, {})
        self.assertEqual(un, ["Algemar Kennel"])

    def test_two_rows_with_the_same_name_are_ambiguous(self):
        row = [""] * 100
        row[1], row[2] = "3", "Ivan Soto"
        m, un, amb = T.match_rows({"Ivan Soto": 5},
                                  T.roster(_grid(extra_rows=[row])))
        self.assertEqual(amb, ["Ivan Soto"])
        self.assertEqual(m, {})


class OnlyEverRaises(unittest.TestCase):
    def test_a_lower_pull_does_not_touch_the_cell(self):
        g = _grid()
        rows = T.roster(g)
        col = T.tk_col(g, MONDAY)
        m, _u, _a = T.match_rows({"Noemi Ontiveros": 9}, rows)   # board holds 12
        plan, protected = T.build_plan(g, col, m, rows)
        self.assertEqual(plan, [])
        self.assertEqual(protected, [])

    def test_a_higher_pull_writes(self):
        g = _grid()
        rows = T.roster(g)
        col = T.tk_col(g, MONDAY)
        m, _u, _a = T.match_rows({"Noemi Ontiveros": 31}, rows)
        plan, _p = T.build_plan(g, col, m, rows)
        self.assertEqual([(p[0].strip(), p[2], p[3]) for p in plan],
                         [("Noemi (Ivette) Ontiveros", 12, 31)])

    def test_an_empty_cell_counts_as_zero(self):
        g = _grid()
        rows = T.roster(g)
        m, _u, _a = T.match_rows({"Zoria Johnson": 21}, rows)
        plan, _p = T.build_plan(g, T.tk_col(g, MONDAY), m, rows)
        self.assertEqual([(p[2], p[3]) for p in plan], [(0, 21)])


class NeverOverwritesAHuman(unittest.TestCase):
    def test_a_typed_mark_is_reported_and_left(self):
        g = _grid()
        rows = T.roster(g)
        m, _u, _a = T.match_rows({"Anthony Coca": 40}, rows)
        plan, protected = T.build_plan(g, T.tk_col(g, MONDAY), m, rows)
        self.assertEqual(plan, [])
        self.assertEqual([(p[0], p[2]) for p in protected],
                         [("Anthony Coca", "X")])


class SandboxTwin(unittest.TestCase):
    """One ownerville pull, two tabs. Ownerville allows a single session per
    account, so the sandbox has to ride the SAME pass -- and it must never be
    able to hurt the live one."""

    class _WS:
        """Enough worksheet for fill_tab: a grid, a title, and a place to
        record what got written."""

        def __init__(self, title, grid):
            self.title, self._g, self.written = title, grid, []

        def get_all_values(self):
            return self._g

        def acell(self, a1, value_render_option=None):
            return type("C", (), {"value": ""})()

        def update_acell(self, a1, value):
            self.written.append((a1, value))

        def batch_update(self, data):
            self.written += [(d["range"], d["values"][0][0]) for d in data]

    def _tab(self, title):
        return self._WS(title, _grid(talk_to=True))

    def test_the_same_pull_lands_on_both_tabs(self):
        live, sand = self._tab("Sales Board WE 9.13"), self._tab(
            "Sales Board WE 9.13" + T.SANDBOX_SUFFIX)
        knocks = {"Zoria Johnson": 120}
        talks = {"Zoria Johnson": 18}
        for ws in (live, sand):
            T.fill_tab(ws, MONDAY, knocks, talks, apply=True,
                       retry=lambda fn, *a, **k: fn(*a, **k))
        self.assertEqual([v for _a1, v in live.written],
                         [v for _a1, v in sand.written])
        self.assertIn(120, [v for _a1, v in live.written])
        self.assertIn(18, [v for _a1, v in live.written])

    def test_the_twin_is_the_tab_name_plus_a_suffix(self):
        self.assertEqual("Sales Board WE 9.13" + T.SANDBOX_SUFFIX,
                         "Sales Board WE 9.13 SANDBOX")

    def test_a_preview_writes_to_neither(self):
        ws = self._tab("Sales Board WE 9.13")
        T.fill_tab(ws, MONDAY, {"Zoria Johnson": 120}, {}, apply=False,
                   retry=lambda fn, *a, **k: fn(*a, **k))
        self.assertEqual(ws.written, [])


class ActiveWindow(unittest.TestCase):
    def test_the_night_ticks_are_no_ops(self):
        at = lambda h: dt.datetime(2026, 8, 31, h, 0, tzinfo=T.CENTRAL)
        self.assertTrue(T.in_active_window(at(6)))
        self.assertTrue(T.in_active_window(at(23)))
        self.assertFalse(T.in_active_window(at(3)))
        self.assertFalse(T.in_active_window(at(0)))



class AppsFormulaGuard(unittest.TestCase):
    """A knock is not a sale. If the day's Apps formula still adds the TK cell,
    the fill must write nothing -- the bug that bit the WE 9.6 tab on
    2026-08-31, when 'EN' was renamed 'TK' and the formula kept pointing at it.
    """

    class _WS:
        def __init__(self, formula):
            self.formula = formula
            self.asked = None

        def acell(self, a1, value_render_option=None):
            self.asked = a1
            return type("C", (), {"value": self.formula})()

    def test_a_formula_that_still_adds_TK_is_caught(self):
        g = _grid()
        apps_c, tk_c = T.day_block(g, MONDAY)
        i_, d, n, tk = (T._a1_col(apps_c + k) for k in (1, 3, 4, 5))
        ws = self._WS(f"=ARRAYFORMULA(IFS({i_}4>=0,({i_}4+{d}4+{n}4+{tk}4)))")
        self.assertTrue(T.apps_counts_tk(ws, apps_c, tk_c, 4))
        self.assertEqual(ws.asked, f"{T._a1_col(apps_c)}4")

    def test_the_repaired_formula_passes(self):
        g = _grid()
        apps_c, tk_c = T.day_block(g, MONDAY)
        i_, d, n, tk = (T._a1_col(apps_c + k) for k in (1, 3, 4, 5))
        ws = self._WS(f"=ARRAYFORMULA(IFS({i_}4>=0,({i_}4+{d}4+{n}4)))")
        self.assertFalse(T.apps_counts_tk(ws, apps_c, tk_c, 4))

    def test_a_marker_branch_naming_TK_is_not_a_false_positive(self):
        """The IFS branches read AE4="X" and must not read as an addition."""
        g = _grid()
        apps_c, tk_c = T.day_block(g, MONDAY)
        i_, d, n, tk = (T._a1_col(apps_c + k) for k in (1, 3, 4, 5))
        ws = self._WS(f'=ARRAYFORMULA(IFS(OR({tk}4="X"),"X",{i_}4>=0,({i_}4+{d}4+{n}4)))')
        self.assertFalse(T.apps_counts_tk(ws, apps_c, tk_c, 4))


if __name__ == "__main__":
    unittest.main()


class MiddleNames(unittest.TestCase):
    """Ownerville carries the legal name, the board carries what people are
    called. 'Justin Carlos Avila' vs 'Justin Avila' (2026-08-31)."""

    def _rows(self, *names):
        return {4 + i: n for i, n in enumerate(names)}

    def test_ownervilles_middle_name_still_finds_the_board_row(self):
        m, un, amb = self._m({"Justin Carlos Avila": 9},
                             self._rows("Justin Avila"))
        self.assertEqual(list(m.values()), [9])
        self.assertEqual((un, amb), ([], []))

    def test_the_board_may_be_the_longer_one(self):
        m, un, _a = self._m({"Charley Perez": 4},
                            self._rows("Charley Alan Perez (Wk 2)"))
        self.assertEqual(list(m.values()), [4])
        self.assertEqual(un, [])

    def test_an_exact_full_name_wins_over_a_first_last_collision(self):
        rows = self._rows("Ivan Soto", "Ivan Munoz Soto")
        m, _u, _a = self._m({"Ivan Munoz Soto": 5}, rows)
        self.assertEqual(m, {5: 5})          # the exact row, not the short one

    def test_two_rows_sharing_first_and_last_stay_ambiguous(self):
        rows = self._rows("Ivan A Soto", "Ivan B Soto")
        m, _u, amb = self._m({"Ivan Soto": 5}, rows)
        self.assertEqual((m, amb), ({}, ["Ivan Soto"]))

    @staticmethod
    def _m(knocks, rows):
        return T.match_rows(knocks, rows)


class TotalsRowGetsATotal(unittest.TestCase):
    """Eve, 2026-08-31: la columna TK tiene que sumar al pie. Four of the seven
    day blocks carried a hard-typed 0 there instead of a formula."""

    class _WS:
        def __init__(self, cells):
            self.cells = cells
            self.written = {}

        def acell(self, a1, value_render_option=None):
            return type("C", (), {"value": self.cells.get(a1, "")})()

        def update_acell(self, a1, value):
            self.written[a1] = value

    def _cols(self):
        g = _grid()
        apps_c, tk_c = T.day_block(g, MONDAY)
        return g, apps_c, tk_c, T._a1_col(apps_c), T._a1_col(tk_c)

    def test_a_hard_typed_zero_is_replaced_by_the_columns_own_total(self):
        g, apps_c, tk_c, A, K = self._cols()
        ws = self._WS({f"{A}79": f'=SUMIF($CG$4:$CG$78,"<>RT",{A}4:{A}78)',
                       f"{K}79": "0"})
        note = T.ensure_tk_total(ws, g, apps_c, tk_c, 79, 4, 78, apply=True)
        self.assertEqual(ws.written,
                         {f"{K}79": f'=SUMIF($CG$4:$CG$78,"<>RT",{K}4:{K}78)'})
        self.assertIn("repaired", note)

    def test_an_existing_formula_is_never_touched(self):
        g, apps_c, tk_c, A, K = self._cols()
        ws = self._WS({f"{A}79": f'=SUMIF($CG$4:$CG$78,"<>RT",{A}4:{A}78)',
                       f"{K}79": f'=SUM({K}4:{K}78)'})
        self.assertIsNone(T.ensure_tk_total(ws, g, apps_c, tk_c, 79, 4, 78,
                                            apply=True))
        self.assertEqual(ws.written, {})

    def test_a_preview_writes_nothing(self):
        g, apps_c, tk_c, A, K = self._cols()
        ws = self._WS({f"{A}79": f'=SUMIF($CG$4:$CG$78,"<>RT",{A}4:{A}78)',
                       f"{K}79": "0"})
        note = T.ensure_tk_total(ws, g, apps_c, tk_c, 79, 4, 78, apply=False)
        self.assertEqual(ws.written, {})
        self.assertIn("would get", note)

    def test_no_apps_formula_to_copy_means_hands_off(self):
        g, apps_c, tk_c, A, K = self._cols()
        ws = self._WS({f"{A}79": "12", f"{K}79": "0"})
        self.assertIsNone(T.ensure_tk_total(ws, g, apps_c, tk_c, 79, 4, 78,
                                            apply=True))
        self.assertEqual(ws.written, {})
