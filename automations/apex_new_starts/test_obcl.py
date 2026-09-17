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


def test_the_watcher_is_not_a_module_any_card_names():
    """The Hub scans the process list for "-m <a card's action module>" to
    find runs it did not start. A watcher launched as run.py therefore made
    the card read RUNNING NOW for two hours and disabled its own button
    (Megan, 2026-09-17: "it's stuck here")."""
    import automations.hub_cards as H
    from automations.apex_new_starts import run as RUN
    import inspect

    named = {a.get("module") for r in H.AUTOMATED_REPORTS
             for a in r.get("actions", []) if a.get("module")}
    watcher = "automations.apex_new_starts.obcl_watch"
    assert watcher not in named, "no card may name the watcher's module"

    src = inspect.getsource(RUN.start_watch)
    assert watcher in src, "and that is what it launches"
    assert '"automations.apex_new_starts.run"' not in src, \
        "never under a module a card names"


def test_a_ticked_row_is_green_too():
    """Megan, 2026-09-17: "it's now checked but not green. We can just make it
    green too please." Same rows as the tick -- a checkbox is easy to miss
    down a column of empty ones."""
    import datetime as dt

    calls = {"batch": [], "format": []}

    class _WS:
        title = "D2D OBCL 9.14"
        def get_all_values(self): return GRID
        def batch_update(self, data): calls["batch"] = data
        def format(self, ranges, fmt): calls["format"] = (ranges, fmt)

    class _SH:
        def worksheets(self): return [_WS()]
        def worksheet(self, t): return _WS()

    import automations.apex_new_starts.obcl as OB
    real = OB.open_by_key
    OB.open_by_key = lambda *a, **k: _SH()
    try:
        assert OB.mark(dt.date(2026, 9, 14), ["Billy Garvin"]) == 1
    finally:
        OB.open_by_key = real

    assert calls["batch"] == [{"range": "F3", "values": [[True]]}]
    assert calls["format"][0] == ["F3"]
    assert calls["format"][1] == {"backgroundColor": OB.GREEN}


def test_names_is_the_fallback_when_the_clipboard_lost_it():
    """The clipboard is the only channel a browser has, so anything copied
    between the run ending and Mark the OBCL being pressed loses the result --
    which is what happened on the first live run (2026-09-17)."""
    from automations.apex_new_starts import run as RUN
    import datetime as dt

    seen = {}
    real = RUN.__dict__.get("_this_monday")
    import automations.apex_new_starts.obcl as OB
    real_mark = OB.mark
    OB.mark = lambda start, added, **k: seen.update(start=start, added=list(added)) or 1
    try:
        assert RUN.mark_obcl(names="Paris Carroll, Bailey Soda") == 0
    finally:
        OB.mark = real_mark

    assert seen["added"] == ["Paris Carroll", "Bailey Soda"]
    assert seen["start"].weekday() == 0, "the Monday of the board week"
