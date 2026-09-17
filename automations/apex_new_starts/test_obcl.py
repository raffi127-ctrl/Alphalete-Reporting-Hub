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
    ticks, unmatched = obcl.plan(
        GRID, ["Emily Flores Castaneda", "Le'derius Arnold"])
    assert ticks == [4, 5]
    assert unmatched == []


def test_only_the_ones_actually_added_are_ticked():
    """A tick or nothing. The green-for-"found" earned its way out: a colour
    meaning "we got as far as attempting them" is not something anybody would
    look at (Megan, 2026-09-17)."""
    ticks, unmatched = obcl.plan(GRID, ["Le'derius Arnold"])
    assert ticks == [5]
    assert unmatched == []


def test_somebody_with_no_row_is_named_not_silently_dropped():
    ticks, unmatched = obcl.plan(GRID, ["Ghost Person"])
    assert ticks == [] and unmatched == ["Ghost Person"]


def test_the_tab_is_the_one_inside_that_board_week():
    titles = ["D2D OBCL", "D2D OBCL 9.7", "D2D OBCL 9.14", "Blue Ink Log"]
    assert obcl.tab_for(dt.date(2026, 9, 14), titles) == "D2D OBCL 9.14"
    assert obcl.tab_for(dt.date(2026, 9, 7), titles) == "D2D OBCL 9.7"
    assert obcl.tab_for(dt.date(2026, 9, 21), titles) is None


def test_the_column_letter():
    assert obcl._a1(1) == "A" and obcl._a1(23) == "W" and obcl._a1(27) == "AA"


def test_the_watcher_only_wakes_for_our_own_marker(monkeypatch):
    """It reads the clipboard, so what it will ACT on has to be narrow: text
    that starts with our marker, and nothing else. Anything else is ignored
    and never stored (Megan, 2026-09-17)."""
    from automations.apex_new_starts import run as RUN

    seen = []
    monkeypatch.setattr(RUN, "mark_obcl", lambda *a, **k: seen.append(1) or 0)
    monkeypatch.setattr(RUN, "WATCH_MINUTES", 0)      # one pass, then stop

    for junk in ("", "214-555-0134", "a password maybe",
                 "APEX-OBCLish but not ours"):
        monkeypatch.setattr(RUN, "_from_clipboard", lambda t=junk: t)
        assert RUN.watch_obcl() == 0
    assert seen == [], "it acted on none of that"


def test_the_watcher_marks_and_stops(monkeypatch):
    from automations.apex_new_starts import run as RUN

    calls = []
    monkeypatch.setattr(RUN, "mark_obcl", lambda *a, **k: calls.append(1) or 0)
    monkeypatch.setattr(RUN, "WATCH_MINUTES", 5)
    monkeypatch.setattr(RUN, "_from_clipboard",
                        lambda: 'APEX-OBCL {"start":"2026-09-14"}')
    assert RUN.watch_obcl() == 0
    assert calls == [1], "marked once, then returned rather than looping"


def test_a_stale_watcher_does_not_block_a_new_one(monkeypatch, tmp_path):
    """A watcher reads the clipboard of whatever session started it, so one
    left over from somewhere else can hold the lock while seeing nothing.
    Past its own window it stops counting."""
    from automations.apex_new_starts import run as RUN
    import datetime as dt, os

    lock = tmp_path / ".obcl-watch.pid"
    monkeypatch.setattr(RUN, "WATCH_LOCK", lock)

    lock.write_text(f"{os.getpid()} {dt.datetime.now().isoformat()}")
    assert RUN._watch_alive() is True, "a fresh one counts"

    old = dt.datetime.now() - dt.timedelta(minutes=RUN.WATCH_MINUTES + 5)
    lock.write_text(f"{os.getpid()} {old.isoformat()}")
    assert RUN._watch_alive() is False, "an old one does not"

    lock.write_text("999999 " + dt.datetime.now().isoformat())
    assert RUN._watch_alive() is False, "nor a dead pid"
