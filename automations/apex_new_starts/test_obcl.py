"""Marking 'Added to APEX' on the week's OBCL tab."""
import datetime as dt

import pytest

from automations.apex_new_starts import obcl


GRID = [
    ["9/14/2026", "", "", "", "", ""],
    ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name",
     "Added to APEX"],
    ["39", "Aimee Garibay", "12:30", "Billy", "Garvin", "FALSE"],
    ["40", "Safiya Mahmoud", "12:30", "Emily", "Flores Castaneda", "FALSE"],
    ["41", "Ana Griffin", "1:30", "Le'derius", "Arnold", "FALSE"],
    ["", "", "", "", "", ""],
]


def test_the_header_is_found_by_its_labels():
    """Row 1 is the week's date, not the header -- and the column was added
    the week it was asked for, so position means nothing."""
    hdr, cols = obcl._layout(GRID)
    assert hdr == 1
    assert cols["added to apex"] == 5


def test_a_renamed_column_says_so_rather_than_guessing():
    bad = [r[:] for r in GRID]
    bad[1][5] = "In Apex?"
    with pytest.raises(RuntimeError, match="Added to APEX"):
        obcl._layout(bad)


def test_two_word_surnames_and_apostrophes_match():
    """The board carries one name; the OBCL keeps first and last apart."""
    ticks, greens, unmatched = obcl.plan(
        GRID, found=[], added=["Emily Flores Castaneda", "Le'derius Arnold"])
    assert ticks == [4, 5]
    assert unmatched == []


def test_found_is_green_and_added_is_ticked():
    """Two states, because they mean different things."""
    ticks, greens, unmatched = obcl.plan(
        GRID, found=["Billy Garvin"], added=["Le'derius Arnold"])
    assert ticks == [5], "only the one that actually went in"
    assert greens == [3, 5], "both, since a tick implies it was found"


def test_somebody_with_no_row_is_named_not_silently_dropped():
    ticks, greens, unmatched = obcl.plan(GRID, found=[], added=["Ghost Person"])
    assert ticks == [] and unmatched == ["Ghost Person"]


def test_the_tab_is_the_one_inside_that_board_week():
    titles = ["D2D OBCL", "D2D OBCL 9.7", "D2D OBCL 9.14", "Blue Ink Log"]
    assert obcl.tab_for(dt.date(2026, 9, 14), titles) == "D2D OBCL 9.14"
    assert obcl.tab_for(dt.date(2026, 9, 7), titles) == "D2D OBCL 9.7"
    assert obcl.tab_for(dt.date(2026, 9, 21), titles) is None


def test_the_column_letter():
    assert obcl._a1(1) == "A" and obcl._a1(23) == "W" and obcl._a1(27) == "AA"
