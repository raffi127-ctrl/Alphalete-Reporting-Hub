"""Sale transfers, against a synthetic form and a synthetic tab.

Run: python -m automations.alphalete_sales_board.test_sale_transfers
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import sale_transfers as T

# cols:      1   2   3        4      5      6        7      8     9     10    11
HEAD_DAY = ["", "", "", "WED", "", "", "", "", "", "", ""]
HEAD_SUB = ["", "", "Rep", "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call"]
WED = dt.date(2026, 9, 16)
FORM_HEAD = ["Timestamp",
             "Your Name ﻿﻿(That's getting the sale transferred to)",
             "Name that the Sale is under", "Date of Sale", "Type of Product Sold",
             "Customers Name", "Cx's Number", "SPM #",
             "Activation Date you Scheduled on Sara+", "Notes", "Status"]


def _grid(rows):
    return [HEAD_DAY, [""] * 11, HEAD_SUB] + rows + [["", "", "TOTALS"] + [""] * 8]


def _row(name, intr="", up="", dtv="", nl=""):
    return ["", "", name, "", intr, up, dtv, nl, "", "", ""]


def _form(*rows):
    return [FORM_HEAD] + [["9/17/2026 3:55:04", to, frm, date, prod, cx, "", spm, "", notes, ""]
                          for to, frm, date, prod, cx, spm, notes in rows]


def _todo(form, day=WED, done=None):
    return T.select(T.read_form(form), day, done or {})


def _cells(ups):
    return {u["range"]: u["values"][0][0] for u in ups}


def test_moves_only_the_form_sale():
    form = _form(("Ana Griffin", "Pranish Shrestha", "9/16/2026", "New Internet",
                  "Terry", "272214275", ""))
    todo, notes, late = _todo(form)
    grid = _grid([_row("Ana Griffin", intr="1"), _row("Pranish Shrestha", intr="3")])
    ups, moved, pn = T.plan(grid, WED, todo)
    # Pranish keeps his own 2; Ana gets the one.
    assert _cells(ups) == {"E4": "2", "E5": "2"}, (_cells(ups), pn)
    assert len(moved) == 1


def test_bonus_and_test_rows_ignored():
    form = _form(("$20 bonus", "Ana Griffin", "9/16/2026", "New Internet", "a", "1", ""),
                 ("owners pay", "Ana Griffin", "9/16/2026", "New Internet", "b", "2", ""),
                 ("owners pay / This new int is Rupinder Singh's actually", "X Y",
                  "9/16/2026", "New Internet", "c", "3", ""),
                 ("Rafael Hidalgo (TEST)", "JD Mascorro", "9/16/2026", "DTV", "d", "4", ""))
    todo, notes, late = _todo(form)
    assert todo == [] and notes == [] and late == [], (todo, notes)


def test_only_the_closed_day_late_rows_listed():
    form = _form(("Ana Griffin", "Pranish Shrestha", "9/15/2026", "New Internet", "a", "1", ""),
                 ("Ana Griffin", "Pranish Shrestha", "9/17/2026", "New Internet", "b", "2", ""))
    todo, notes, late = _todo(form)
    assert todo == [] and [t["date_raw"] for t in late] == ["9/15/2026"]


def test_lines_from_notes_and_multi_product():
    m, unknown = T.products("New Internet, DTV, New Line", "It was 1 internet 1 DTV 4 Lines")
    assert m == {"Int": 1, "DTV": 1, "NL": 4} and not unknown, m
    assert T.products("New Internet, New Line", "Fiber 1 gig and 2 ported lines")[0] == \
        {"Int": 1, "NL": 2}
    assert T.products("New Internet, Other", "")[1] == ["other"]


def test_from_short_moves_nothing():
    form = _form(("Ana Griffin", "Pranish Shrestha", "9/16/2026", "New Internet, New Line",
                  "a", "1", "3 lines"))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Ana Griffin"), _row("Pranish Shrestha", intr="1", nl="2")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert ups == [] and moved == [] and "NOT moved" in notes[0], notes


def test_from_off_that_day_is_plus_only():
    form = _form(("Ana Griffin", "Rhea Mckee", "9/16/2026", "New Internet", "a", "1", ""))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Ana Griffin", intr="5"), _row("Rhea McKee", intr="x")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert _cells(ups) == {"E4": "6"}, (_cells(ups), notes)


def test_manager_login_is_plus_only():
    form = _form(("Ana Griffin", "JD Mascorro", "9/16/2026", "New Internet", "a", "1", ""))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Ana Griffin")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert _cells(ups) == {"E4": "1"}, (_cells(ups), notes)


def test_to_with_status_is_left_alone():
    form = _form(("Kenneth Guzman", "Anthony Marchetti", "9/16/2026", "Upgrade", "a", "1", ""))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Kenneth Guzman", intr="X"), _row("Anthony Marchetti", up="1")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert ups == [] and "roll-call" in notes[0], notes


def test_duplicate_submission_counted_once_and_state_skips():
    row = ("Ana Griffin", "Pranish Shrestha", "9/16/2026", "New Internet", "a", "1", "")
    todo, notes, _l = _todo(_form(row, row))
    assert len(todo) == 1 and "counted once" in notes[0]
    todo2, _n, _l = _todo(_form(row), done={todo[0]["key"]: "2026-09-17"})
    assert todo2 == []


def test_unknown_name_not_guessed():
    form = _form(("Andres", "Pranish Shrestha", "9/16/2026", "New Internet", "a", "1", ""))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Andres Lopez"), _row("Andres Ruiz"), _row("Pranish Shrestha", intr="1")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert ups == [] and moved == [], notes


def test_misspelled_name_is_read():
    form = _form(("Rupinder Singh", "Pranish shresta", "9/16/2026", "New Internet", "a", "1", ""),
                 ("Kenneth guzman", "kelvinton scar bough", "9/16/2026", "Upgrade", "b", "2", ""))
    todo, _n, _l = _todo(form)
    grid = _grid([_row("Rupinder Singh (Wk 3)"), _row("Pranish Shrestha", intr="1"),
                  _row("Kenneth Guzman"), _row("Kelvinton ( BO ) Scarbough", up="1")])
    ups, moved, notes = T.plan(grid, WED, todo)
    assert _cells(ups) == {"E4": "1", "E5": "", "F6": "1", "F7": ""}, (_cells(ups), notes)


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("ok -- %d tests" % n)
