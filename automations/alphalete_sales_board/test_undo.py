"""Taking back a row we added — and refusing to take back one we didn't."""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import fill, state as S

HEAD_DAY = ["", "", "", "MON", "", "", "", "", "", "", "",
            "TUES"] + [""] * 8
HEAD_SUB = ["", "", "Rep", "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx",
            "Roll Call",
            "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call", ""]
MONDAY = dt.date(2026, 8, 24)
TUESDAY = dt.date(2026, 8, 25)


def _grid(rows):
    return [HEAD_DAY, [""] * 20, HEAD_SUB] + rows + [["", "", "TOTALS"] + [""] * 17]


def _row(name, mon=("", "", "", "", ""), tue=("", "", "", "", "")):
    return (["", "", name] + list(mon) + ["", "", ""]
            + list(tue) + ["", "", ""] + [""])


class FakeWS:
    title = "Sales Board WE 8.30"
    def __init__(self): self.writes = None
    def batch_update(self, updates, **kw): self.writes = updates


def test_clears_the_row_we_added():
    grid = _grid([_row("Kelvinton Scarbrough", mon=("", "1", "", "", ""))])
    ws = FakeWS()
    ok, note = fill.remove_rep(ws, grid, 4, "Kelvinton Scarbrough", MONDAY)
    assert ok, note
    ranges = sorted(u["range"] for u in ws.writes)
    assert "C4" in ranges, ranges              # the name
    assert all(u["values"] == [[""]] for u in ws.writes)


def test_refuses_when_somebody_has_since_edited_the_row():
    grid = _grid([_row("Someone Else Entirely")])
    ws = FakeWS()
    ok, note = fill.remove_rep(ws, grid, 4, "Kelvinton Scarbrough", MONDAY)
    assert not ok and ws.writes is None
    assert "edited" in note, note


def test_refuses_a_row_carrying_a_roll_call_letter():
    grid = _grid([_row("Kelvinton Scarbrough", mon=("X", "X", "", "", ""))])
    ws = FakeWS()
    ok, note = fill.remove_rep(ws, grid, 4, "Kelvinton Scarbrough", MONDAY)
    assert not ok and ws.writes is None
    assert "roll-call" in note, note


def test_earlier_days_are_named_not_silently_dropped():
    # Cleared on TUESDAY: Monday's numbers were on the duplicate row and this
    # sweep only ever writes today, so they must be called out by name.
    grid = _grid([_row("Kelvinton Scarbrough",
                       mon=("", "2", "", "1", ""), tue=("", "1", "", "", ""))])
    ws = FakeWS()
    ok, note = fill.remove_rep(ws, grid, 4, "Kelvinton Scarbrough", TUESDAY)
    assert ok, note
    assert "Monday" in note and "2 Int" in note, note
    assert "by hand" in note, note
    assert "Tuesday" not in note, note      # today restores itself


def test_only_rows_we_recorded_are_findable():
    data = S.record_added({}, MONDAY, "KELVINTON SCARBROUGH",
                          "Kelvinton Scarbrough", 65)
    assert S.added_row(data, "kelvinton scarbrough")["row"] == 65
    assert S.added_row(data, "SOMEBODY ELSE") is None
    data = S.forget_added(data, "KELVINTON SCARBROUGH")
    assert S.added_row(data, "KELVINTON SCARBROUGH") is None


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
