"""The board-write safety rules, against a synthetic tab.

These are the four promises run.py's docstring makes to a job that writes 150
times a day with nobody watching. A regression in any of them is silent damage
to a sheet people are paid off, so they are tested here rather than trusted.

Run: python -m automations.alphalete_sales_board.test_fill
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import fill

# cols:      1     2     3        4      5      6        7      8     9     10    11
HEAD_DAY = ["", "", "", "MON", "", "", "", "", "", "", "", "TUES", "", "", "", "", "", "", "", ""]
HEAD_SUB = ["", "", "Rep", "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call",
            "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call", ""]
MONDAY = dt.date(2026, 8, 24)     # a Monday
TUESDAY = dt.date(2026, 8, 25)


def _grid(rows):
    return [HEAD_DAY, [""] * 20, HEAD_SUB] + rows + [["", "", "TOTALS"] + [""] * 17]


def _row(name, mon=("", "", "", "", ""), tue=("", "", "", "", "")):
    # Apps, Int, Int Up, DTV, NL then EN/Cx/Roll Call
    return (["", "", name] + list(mon) + ["", "", ""]
            + list(tue) + ["", "", ""] + [""])


def test_writes_todays_four_cells():
    grid = _grid([_row("Jane Doe")])
    ups, notes = fill.plan(grid, MONDAY,
                           [{"board_name": "Jane Doe",
                             "metrics": {"Int": 2, "Int Up": 0, "DTV": 1, "NL": 0}}])
    got = {u["range"]: u["values"][0][0] for u in ups}
    # E = Int, G = DTV. Apps (D) and Roll Call (K) are absent from the plan.
    assert got == {"E4": "2", "G4": "1"}, got
    assert not any(r.startswith(("D", "K")) for r in got), got


def test_zero_is_written_as_blank_not_as_a_zero():
    grid = _grid([_row("Jane Doe", mon=("", "1", "", "", ""))])
    ups, _ = fill.plan(grid, MONDAY,
                       [{"board_name": "Jane Doe",
                         "metrics": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}])
    assert ups == [], ups     # nothing changes; a literal 0 is never written


def test_a_number_is_never_blanked():
    # The board says 2 Int. A short export says nothing. The 2 stays.
    grid = _grid([_row("Jane Doe", mon=("", "2", "", "", ""))])
    ups, notes = fill.plan(grid, MONDAY,
                           [{"board_name": "Jane Doe",
                             "metrics": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 0}}])
    assert ups == [], ups
    assert any("no se borra" in n or "NO se borra" in n for n in notes), notes


def test_roll_call_status_is_never_overwritten():
    grid = _grid([_row("Jane Doe", mon=("X", "X", "", "", ""))])
    ups, notes = fill.plan(grid, MONDAY,
                           [{"board_name": "Jane Doe",
                             "metrics": {"Int": 3, "Int Up": 0, "DTV": 0, "NL": 0}}])
    assert ups == [], ups
    assert any("roll-call status" in n for n in notes), notes


def test_only_the_asked_for_day_is_touched():
    grid = _grid([_row("Jane Doe")])
    ups, _ = fill.plan(grid, TUESDAY,
                       [{"board_name": "Jane Doe",
                         "metrics": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}])
    got = [u["range"] for u in ups]
    assert got == ["M4"], got      # Tuesday's Int, not Monday's


def test_a_rep_who_is_not_on_the_roster_is_reported():
    grid = _grid([_row("Jane Doe")])
    ups, notes = fill.plan(grid, MONDAY,
                           [{"board_name": "Ghost Rider",
                             "metrics": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}])
    assert ups == [], ups
    assert any("Ghost Rider" in n for n in notes), notes


def test_names_below_totals_are_not_the_roster():
    grid = _grid([_row("Jane Doe")]) + [_row("Jane Doe")]   # a second Jane below TOTALS
    names = fill.board_names(grid)
    assert names == ["Jane Doe"], names


def test_free_roster_row_finds_the_prebuilt_blank():
    grid = _grid([_row("Jane Doe"), _row(""), _row("Rex Ryan")])
    assert fill.free_roster_row(grid) == 5, fill.free_roster_row(grid)


def test_no_blank_row_refuses_rather_than_appending_below_totals():
    # The TOTALS row is =SUMIF($CG$4:$CG$79,...) — a name below 79 is silently
    # left out of every total, which is why this must never "just append".
    class FakeWS:
        title = "Sales Board WE 8.30"
        def update_acell(self, *a):
            raise AssertionError("must not write when the roster is full")
    grid = _grid([_row("Jane Doe")])          # no blank rows
    row, note = fill.add_rep(FakeWS(), grid, "New Person")
    assert row is None, row
    assert "INSERTED" in note and "every total" in note, note


def test_a_new_person_is_added_not_second_guessed():
    # 2026-08-27: "Aaron Corona" scored 0.62 against "Milagros Colon" on
    # coincidental letters and was refused, so a real rep sold all day with no
    # row. Refusing wrongly is the expensive mistake; adding wrongly is now
    # undone by a chat reply.
    board = ["Milagros Colon (Wk 2)", "Michael Ortiz"]
    assert fill.near_matches("AARON CORONA", board) == [], \
        fill.near_matches("AARON CORONA", board)
    assert fill.near_matches("PALOMA FUNDERBURK", board) == []
    assert fill.near_matches("MIGUEL ANGEL RIVERA", board) == []


def test_near_matches_blocks_a_probable_duplicate():
    board = ["Michael Ortiz", "Jane Doe"]
    assert fill.near_matches("MIKE ORTIZ", board) == ["Michael Ortiz"], \
        fill.near_matches("MIKE ORTIZ", board)
    assert fill.near_matches("Michal Ortiz", board), "a typo must be caught too"
    # a nickname sharing the surname is still caught
    assert fill.near_matches("MIKEY ORTIZ", board) == ["Michael Ortiz"]


def test_near_matches_allows_a_genuinely_new_person():
    board = ["Michael Ortiz", "Jane Doe"]
    assert fill.near_matches("ANTONIO DAVIS", board) == [], \
        fill.near_matches("ANTONIO DAVIS", board)


def test_tab_title_is_the_weeks_sunday():
    assert fill.tab_title(MONDAY) == "Sales Board WE 8.30"
    assert fill.tab_title(dt.date(2026, 8, 30)) == "Sales Board WE 8.30"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
