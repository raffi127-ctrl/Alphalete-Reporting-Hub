"""Finishing a new rep's row the way Raf does it by hand."""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import fill

MONDAY = dt.date(2026, 8, 24)
WEDNESDAY = dt.date(2026, 8, 26)

# Row 1 carries the real labels; row 3 says "REP" over four different columns,
# which is why nothing here may use an index.
R1 = ["", "", "", "MON", "", "", "", "", "", "", "",
      "Trainer", "DRUG TEST", "Field Status", "Campaign", "Team",
      "Leadership Status", "Start Date", "Location"]
R3 = ["", "", "Rep", "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx",
      "Roll Call", "REP", "STATUS", "", "", "", "", "REP", ""]


def _grid(reps, classroom):
    rows = [R1, [""] * 19, R3]
    rows += reps
    rows += [["", "", "TOTALS"] + [""] * 16]
    rows += [[""] * 19]
    rows += [["", "", "Classroom", "Trainers", "", "", "", "", "", "", "Location"] + [""] * 8]
    rows += classroom
    return rows


def _rep(name, trainer="", team=""):
    r = ["", "", name] + [""] * 8 + [trainer, "", "", "", team, "", ""]
    return r + [""] * (19 - len(r))


def test_fills_everything_the_way_a_person_would():
    grid = _grid(
        [_rep("Pranish Shrestha", team="Hashiras"), _rep("Aaron Corona")],
        [["", "", "Aaron Corona", "Pranish", "", "", "", "", "", "", "Fort Worth"]])
    ups, notes = fill.new_rep_details(grid, "Aaron Corona", WEDNESDAY)
    got = {u["range"]: u["values"][0][0] for u in ups}
    assert "Pranish Shrestha" in got.values(), got     # full name, not "Pranish"
    assert "1st Wk" in got.values(), got
    assert "Fiber" in got.values(), got
    assert "Hashiras" in got.values(), got             # the TRAINER's team
    assert "In Training" in got.values(), got
    assert "8/24/2026" in got.values(), got            # the week's MONDAY, not today


def test_a_nickname_in_the_block_is_matched_on_the_surname():
    # 2026-08-27: SaraPlus said "SHUMINIQUE VALENTINE", the block said "Nikki
    # Valentine", and she was added with no trainer, team or location.
    grid = _grid(
        [_rep("Willie Henderson", team="Ceaseless"), _rep("Shuminique Valentine")],
        [["", "", "Nikki Valentine", "Willie Henderson", "", "", "", "", "", "",
          "Dallas"]])
    ups, notes = fill.new_rep_details(grid, "Shuminique Valentine", WEDNESDAY)
    got = [u["values"][0][0] for u in ups]
    assert "Willie Henderson" in got, got
    assert "Ceaseless" in got, got
    assert "Dallas" in got, got                      # Location comes from the block
    assert any("surname" in n for n in notes), notes


def test_two_people_sharing_a_surname_is_left_for_a_person():
    grid = _grid(
        [_rep("Willie Henderson", team="Ceaseless"), _rep("Shuminique Valentine")],
        [["", "", "Nikki Valentine", "Willie Henderson", "", "", "", "", "", "", "Dallas"],
         ["", "", "Carl Valentine", "Somebody Else", "", "", "", "", "", "", "Plano"]])
    ups, notes = fill.new_rep_details(grid, "Shuminique Valentine", WEDNESDAY)
    got = [u["values"][0][0] for u in ups]
    assert "Willie Henderson" not in got and "Ceaseless" not in got, got
    assert any("shares a surname" in n for n in notes), notes


def test_no_classroom_entry_still_fills_what_it_knows():
    grid = _grid([_rep("Aaron Corona")], [])
    ups, notes = fill.new_rep_details(grid, "Aaron Corona", WEDNESDAY)
    got = [u["values"][0][0] for u in ups]
    assert "1st Wk" in got and "Fiber" in got and "In Training" in got, got
    assert not any(v == "Hashiras" for v in got)
    assert any("Trainer and Team left blank" in n for n in notes), notes


def test_an_ambiguous_trainer_is_left_blank_not_guessed():
    grid = _grid(
        [_rep("Pranish Shrestha", team="Hashiras"),
         _rep("Pranish Gurung", team="Velocity"), _rep("Aaron Corona")],
        [["", "", "Aaron Corona", "Pranish", "", "", "", "", "", "", "Fort Worth"]])
    ups, notes = fill.new_rep_details(grid, "Aaron Corona", WEDNESDAY)
    got = [u["values"][0][0] for u in ups]
    assert "Hashiras" not in got and "Velocity" not in got, got
    assert any("matches 2 reps" in n for n in notes), notes


def test_start_date_is_the_weeks_monday_whatever_day_it_runs():
    grid = _grid([_rep("Aaron Corona")], [])
    for day in (MONDAY, WEDNESDAY, dt.date(2026, 8, 29)):
        ups, _ = fill.new_rep_details(grid, "Aaron Corona", day)
        assert "8/24/2026" in [u["values"][0][0] for u in ups], day


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
