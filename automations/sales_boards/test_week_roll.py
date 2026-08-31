"""Where the Vantura week roll can quietly go wrong.

Two of these pin bugs that were live while the module was being written:

  * the campaign subtotals under the reps were found by "any row below the reps
    with something in col L" — on the real board that also matched the stats
    block ('Apps', row 53), so a roll would have written 'Last Wk' on top of
    somebody's data;
  * the gold cell's dropdown was rendered off the NUMBERS in WeekData!J, which
    cannot hold a trailing zero: the week ending 9/20 came out "9.2", and
    picking it would key every day cell `<REP>|9.2` while the fill writes
    `<REP>|9.20` — the same blank-board failure as 2026-08-24.

Run:  python -m automations.sales_boards.test_week_roll
"""
from __future__ import annotations

import datetime as dt

from automations.sales_boards import week_roll as W
from automations.sales_boards.zeros import we_label

HDR = ["#", "REP", "Current Week", "Last Wk", "Monday", "Tuesday", "Wednesday",
       "Thursday", "Friday", "Saturday", "Sunday", "Campaign"]


def _grid():
    """The real board's shape: header, reps with a '#', campaign subtotals and
    TOTAL without one, then the stats block that also names campaigns."""
    return [
        ["", "", "Vantura Master Salesboard"],
        ["WE", "8.30", " Week Ending 8.30"],
        ["", "", "This Wk", "Last Wk", "MON (24)", "TUE (25)", "WED (26)",
         "THU (27)", "FRI (28)", "SAT (29)", "SUN (30)"],
        HDR,
        ["1", "Diego Borres", "24", "19", "4", "5", "X", "6", "9", "", "",
         "B2B"],
        ["2", "Nico Murrugarra", "0", "3", "F", "F", "F", "F", "F", "", "",
         "B2B"],
        ["3", "Juliett Ortega", "1", "0", "", "", "1", "", "", "", "", "BOX"],
        ["", "AT&T (B2B)", "24", "145", "4", "5", "0", "6", "9", "0", "0",
         "B2B"],
        ["", "BOX", "1", "66", "0", "0", "1", "0", "0", "0", "0", "BOX"],
        ["", "TOTAL", "25", "211", "4", "5", "1", "6", "9", "0", "0"],
        [],
        ["", "% on the Board", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "", "",
         "Headcount by Campaign", "Apps"],
        ["", "All AT&T B2B Reps", "0", "0", "0", "0", "0", "0", "", "",
         "AT&T (B2B)", "B2B"],
    ]


def test_reps_stop_where_the_numbering_stops():
    b = W.Board(_grid())
    assert [r["row"] for r in b.reps] == [5, 6, 7], [r["row"] for r in b.reps]
    assert b.reps[1]["days"] == ["F", "F", "F", "F", "F", "", ""]


def test_campaign_rows_do_not_reach_the_stats_block():
    b = W.Board(_grid())
    assert {c: r["row"] for c, r in b.campaigns.items()} == {"B2B": 8, "BOX": 9}
    # row 13 also says "B2B" in the campaign column, below TOTAL and a blank.
    assert all(r["row"] < 10 for r in b.campaigns.values())


def test_campaign_last_wk_comes_from_what_the_board_showed():
    b = W.Board(_grid())
    # 145/66 was week 8.23 and is what stayed on the board when the first roll
    # forgot these two cells; the closing week is 24/1.
    assert b.campaigns["B2B"]["last_wk"] == "145"
    assert b.campaigns["B2B"]["this_wk"] == "24"
    assert b.campaigns["BOX"]["this_wk"] == "1"


def test_columns_are_found_by_header_not_by_index():
    shifted = [(["spacer"] + row if row else []) for row in _grid()]
    b = W.Board(shifted)
    assert W.a1(b.c_name) == "C" and W.a1(b.c_last) == "E"
    assert W.a1(b.c_days[0]) == "F" and W.a1(b.c_days[-1]) == "L"
    assert [r["name"] for r in b.reps][0] == "Diego Borres"


def test_day_formula_keys_on_the_rep_name_and_the_gold_cell():
    b = W.Board(_grid())
    first = b.day_formulas(5)[0]
    assert 'MATCH($B5&"|"&$B$2' in first, first
    assert first.startswith('=IFERROR(INDEX(WeekData!$B$2:$B$5000,')
    assert b.day_formulas(5)[6].startswith('=IFERROR(INDEX(WeekData!$H$2:$H$5000,')
    assert len(b.day_formulas(5)) == 7


def test_a_week_ending_in_zero_keeps_its_zero():
    """9.20 is the next one; 8.30 is the one that broke the board twice."""
    for sunday, label in ((dt.date(2026, 9, 20), "9.20"),
                          (dt.date(2026, 8, 30), "8.30")):
        assert sunday.weekday() == 6
        assert we_label(sunday) == label
        assert we_label(sunday - dt.timedelta(days=6)) == label   # its Monday
        # J holds the number, which loses the zero: the label must not come
        # from there.
        assert str(float(label)) != label


def test_sunday_of_and_as_number():
    assert W.sunday_of(46271) == dt.date(2026, 9, 6)
    assert W.sunday_of("") is None and W.sunday_of(None) is None
    assert W.as_number("7") == 7 and W.as_number("2.5") == 2.5
    assert W.as_number("X") == "X" and W.as_number("") == ""


def test_a1():
    got = [W.a1(n) for n in (1, 4, 11, 12, 26, 27, 45)]
    assert got == ["A", "D", "K", "L", "Z", "AA", "AS"], got


def _main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   " + name)
            except AssertionError as e:
                fails += 1
                print("  FAIL " + name + ": " + str(e))
    print(("FAILED " + str(fails)) if fails else "all green")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
