"""A board rolled FORWARD still renders the week that just closed.

2026-09-14: the week roll moved to 08:20, the Monday BOX board only renders at
the 08:50 / 09:40 rungs, so it met a rolled board, held, and the only fix on
offer was flipping the LIVE gold cell back and forth around a post. The roll's
snapshot holds the closing week's board; these pin how it is found and how it
is written back onto the temp copy.

Run:  python -m automations.sales_boards.test_rolled_forward
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

import automations.sales_boards.run as R

SUN_913, SUN_920 = dt.date(2026, 9, 13), dt.date(2026, 9, 20)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]


def _grid():
    """A rolled board: B2 on 9.20, day cells blank (formulas), 'Last Wk' holding
    the closing week's totals, one rep added after the roll — and the blank
    separator row the live board grew on 2026-09-14 between B2B and BOX."""
    return [
        [""],
        ["WE", "9.20"],
        ["#", "REP", "Current Week", "Last Wk"] + DAYS + ["Campaign"],
        ["1", "ANA", "0", "6"] + [""] * 7 + ["B2B"],
        ["2", "NEW GUY", "0", ""] + [""] * 7 + ["B2B"],
        [],
        ["3", "BEA", "0", "5"] + [""] * 7 + ["BOX"],
        ["", "BOX", "0", "5"] + [""] * 7 + ["BOX"],
        ["", "TOTAL"],
        ["", "BOX", "Apps"],               # stats block: must never be written
    ]


SNAP = {
    "from_week": "9.13", "to_week": "9.20",
    "reps": [
        {"name": "ANA", "days": ["1", "", "2", "", "", "F", "3"],
         "last_wk": "7", "campaign": "B2B"},
        {"name": "BEA", "days": ["", "", "", "", "", "", "5"],
         "last_wk": "9", "campaign": "BOX"},
        {"name": "GONE", "days": ["1"] * 7, "last_wk": "4", "campaign": "BOX"},
    ],
    "campaigns": {"BOX": {"row": 8, "name": "BOX", "last_wk": "30"}},
}


def test_rewind_puts_the_closing_week_back_by_label():
    writes, gone = R.rewind_writes(_grid(), SNAP)
    got = {w["range"]: w["values"] for w in writes}
    assert got["E4:K4"] == [[1, "", 2, "", "", "F", 3]], got
    assert got["D4"] == [[7]], got           # Last Wk = the week BEFORE 9.13
    assert got["D8"] == [[30]], got          # campaign total's hand-typed Last Wk
    assert gone == ["GONE"], gone


def test_rewind_reaches_reps_below_a_blank_row():
    """week_roll's Board stops at the first blank row; on the live board that
    was 6 reps of 46, with every BOX rep below the gap."""
    writes, _ = R.rewind_writes(_grid(), SNAP)
    got = {w["range"]: w["values"] for w in writes}
    assert got["E7:K7"] == [["", "", "", "", "", "", 5]], got
    assert got["D7"] == [[9]], got
    assert "D10" not in got, got             # below TOTAL: the stats block


def test_rewind_leaves_a_rep_added_after_the_roll_alone():
    writes, _ = R.rewind_writes(_grid(), SNAP)
    assert not any(w["range"].endswith("5") for w in writes), writes


def _write(d: Path, name: str, blob) -> None:
    (d / name).write_text(json.dumps(blob), encoding="utf-8")


def test_snapshot_found_for_the_roll_that_left_the_week():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        _write(d, "week_roll_9.13_to_9.20_2026-09-14.json", SNAP)
        snap = R.roll_snapshot("9.13", SUN_920, out_dir=d)
        assert snap and snap["from_week"] == "9.13"


def test_no_snapshot_means_hold():
    """Rolled by hand from the dropdown (no snapshot), or a different roll:
    nothing trustworthy to render, so the pass must still hold."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        assert R.roll_snapshot("9.13", SUN_920, out_dir=d) is None
        _write(d, "week_roll_9.6_to_9.13_2026-09-07.json",
               dict(SNAP, from_week="9.6", to_week="9.13"))
        assert R.roll_snapshot("9.13", SUN_920, out_dir=d) is None


def test_trailing_zero_week_label():
    """8.30 must be looked up as '8.30', never '8.3'."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        _write(d, "week_roll_8.23_to_8.30_2026-08-24.json",
               dict(SNAP, from_week="8.23", to_week="8.30"))
        assert R.roll_snapshot("8.23", dt.date(2026, 8, 30), out_dir=d)


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
