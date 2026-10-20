"""City on the Sales Board vs Blue Ink: what gets written and what doesn't."""
from __future__ import annotations

from automations.sales_board_fixer import city_check as CC


def _grid(rows):
    # row 1 labels, row 2 blank, row 3 sub-headers, reps from row 4, TOTALS after
    r1 = ["", "", "", "MON", "", "Location"]
    g = [r1, [""] * 6, ["", "", "Rep", "Apps", "", "REP"]]
    g += [["", "", n, "", "", city] for n, city in rows]
    g += [["", "", "TOTALS", "", "", ""]]
    return g


def test_location_found_by_label():
    assert CC.location_col(_grid([])) == 6
    assert CC.location_col([["", "Where"]]) == 0


def test_blank_is_filled_same_is_left_typo_is_fixed():
    g = _grid([("Aundre Browder", ""), ("Hank Tran", "Arlington"),
               ("Amjad (MJ) Malhas", "Mckinny"), ("Lian Reyes", "Richardson")])
    rows = CC.reps(g, 6)
    changes, missing = CC.plan(rows, {
        "Aundre Browder": "DALLAS", "Hank Tran": "arlington ",
        "Amjad (MJ) Malhas": "mckinney", "Lian Reyes": ""})
    got = {c.name: (c.before, c.after) for c in changes}
    assert got == {"Aundre Browder": ("", "Dallas"),
                   "Amjad (MJ) Malhas": ("Mckinny", "McKinney")}
    assert [n for _, n, _ in missing] == ["Lian Reyes"]


def test_a_typo_on_the_packet_does_not_beat_the_board():
    # 2026-10-20: Blue Ink said 'Arlingotn' for Hank Tran
    g = _grid([("Hank Tran", "Arlington"), ("Zoria Johnson", "Fort Worth"),
               ("Kayla Sprague", ""), ("Savannah Moreno", "Carrolton"),
               ("Alexis Renteria", "")])
    changes, _ = CC.plan(CC.reps(g, 6), {
        "Hank Tran": "Arlingotn", "Zoria Johnson": "Arlington",
        "Kayla Sprague": "Arlington", "Savannah Moreno": "Carrollton",
        "Alexis Renteria": "Carrollton"})
    got = {c.name: c.after for c in changes}
    assert "Hank Tran" not in got
    assert got["Zoria Johnson"] == "Arlington"          # a real move still moves
    assert got["Savannah Moreno"] == "Carrollton"       # the board's typo is fixed


def test_rows_point_at_the_rep():
    g = _grid([("A One", ""), ("B Two", "Plano")])
    assert CC.reps(g, 6) == [(4, "A One", ""), (5, "B Two", "Plano")]


def test_tidy_city():
    assert CC.tidy_city("  FORT   WORTH ") == "Fort Worth"
    assert CC.tidy_city("mckinney") == "McKinney"
    assert CC.tidy_city("Mc") == "Mc"


def test_dm_lists_only_reps_still_blank():
    blanks = [(19, "Samajai Hoy (Wk 2)", ""), (23, "Geovany Torres", "")]
    text = CC.dm_text("Sales Board WE 10.25", blanks,
                      {"Geovany Torres": "no signed Blue Ink packet"})
    assert "2 reps" in text and "Samajai Hoy (Wk 2)" in text
    assert "- Geovany Torres (no signed Blue Ink packet)" in text
    assert CC.dm_text("Sales Board WE 10.25", [], {}) == ""
