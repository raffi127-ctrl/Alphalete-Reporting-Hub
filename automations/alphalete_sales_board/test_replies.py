"""Either order, real names, and a refusal when it genuinely can't tell."""
from __future__ import annotations

from automations.alphalete_sales_board import replies as R

BOARD = ["Kelvinton ( BO ) Scarbough (Wk 3)", "Jane Doe", "Andres Mejia (Wk 2)",
         "Nima Aweida", "Hayden Wilson (Wk 3)"]
PENDING = ["KELVINTON SCARBROUGH", "LEMSY VAZQUEZ"]


def test_parses_the_shapes_people_actually_type():
    assert R.parse_pair("Bo=Kelvinton") == ("Bo", "Kelvinton")
    assert R.parse_pair("bo = kelvinton") == ("bo", "kelvinton")
    assert R.parse_pair("Bo is Kelvinton") == ("Bo", "Kelvinton")
    assert R.parse_pair("Bo == Kelvinton.") == ("Bo", "Kelvinton")
    assert R.parse_pair("yeah that's him") is None
    assert R.parse_pair("") is None


def test_either_order_gives_the_same_answer():
    a = R.resolve("Bo", "Kelvinton", BOARD, PENDING)
    b = R.resolve("Kelvinton", "Bo", BOARD, PENDING)
    assert a[:2] == ("KELVINTON SCARBROUGH", "Kelvinton ( BO ) Scarbough (Wk 3)"), a
    assert b[:2] == a[:2], (a, b)


def test_bo_is_found_inside_the_parentheses():
    # Everything else in this package strips parentheticals; here they ARE the
    # match. "Bo" appears nowhere else in that row.
    assert R._score("bo", "Kelvinton ( BO ) Scarbough (Wk 3)") >= 0.9


def test_both_names_on_one_row_is_a_confirmation_not_a_complaint():
    # The first live test, 2026-08-27. Kelvinton's alias already existed, so
    # nobody was "missing" and resolve() refused — the room got "I couldn't
    # tell which is which" for a message that was perfectly clear.
    assert R.same_person_already("Kelvinton", "Bo", BOARD) == BOARD[0]
    assert R.same_person_already("Bo", "Kelvinton", BOARD) == BOARD[0]


def test_two_different_people_are_not_the_same_row():
    assert R.same_person_already("Kelvinton", "Jane", BOARD) is None
    assert R.same_person_already("Nima", "Hayden", BOARD) is None


def test_a_stray_line_resolves_to_nothing():
    who = R.resolve("lunch", "tacos", BOARD, PENDING)
    assert who[0] is None and "couldn't place" in who[2], who


def test_a_name_on_the_board_but_not_pending_is_refused():
    # Both sides on the board = nobody to create an alias FOR.
    who = R.resolve("Jane", "Nima", BOARD, PENDING)
    assert who[0] is None, who


def test_can_read_reports_why_not():
    ok, why = R.can_read()
    assert isinstance(ok, bool)
    if not ok:
        assert why, "a refusal must say why"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
