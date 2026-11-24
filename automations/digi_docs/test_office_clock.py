"""A start time is on the OFFICE's clock, not the machine's.

Megan, 2026-11-24: "we'll need to make sure that we're reading the calendar in
the right time zone."

    python -m pytest automations/digi_docs/test_office_clock.py -q
"""
import datetime as dt

import pytest

from automations.digi_docs import config as C
from automations.digi_docs import roster


class _C:
    """Just enough of a Candidate for due_now."""

    def __init__(self, name, start_time):
        self.name, self.start_time = name, start_time


def test_alphalete_is_still_central():
    """It was the only answer until today, and it stays the default: an office
    that has not been asked keeps what it has had since August."""
    assert C.office_tz() == "America/Chicago"
    assert C.office_tz("raf") == "America/Chicago"


def test_an_offices_own_answer_wins(monkeypatch):
    from automations.eco_onboarding import store as store
    monkeypatch.setattr(store, "read",
                        lambda key, book=None: {C.TZ_COLUMN: "America/Phoenix"})
    assert C.office_tz("someone") == "America/Phoenix"


def test_a_hand_listed_office_is_used_when_there_is_no_answer(monkeypatch):
    from automations.eco_onboarding import store as store
    monkeypatch.setattr(store, "read", lambda key, book=None: {})
    monkeypatch.setitem(C.OFFICE_TZ_BY_KEY, "west", "America/Los_Angeles")
    assert C.office_tz("west") == "America/Los_Angeles"


def test_an_unreachable_sheet_does_not_move_anybodys_send(monkeypatch):
    from automations.eco_onboarding import store as store
    monkeypatch.setattr(store, "read",
                        lambda key, book=None: (_ for _ in ()).throw(OSError("no")))
    assert C.office_tz("someone") == C.OFFICE_TZ


def test_a_typo_in_a_zone_falls_back_to_the_machine(monkeypatch):
    """A wrong zone name must not move every send by a random amount."""
    monkeypatch.setitem(C.OFFICE_TZ_BY_KEY, "oops", "Mars/Olympus")
    monkeypatch.setattr(C, "office_tz", lambda key="": "Mars/Olympus")
    got = C.office_now("oops", dt.datetime(2026, 11, 24, 9, 0))
    assert got.hour == 9


# ------------------------------------------------- what it actually changes

def _due_at(hour, minute, tz, start_time="9:00"):
    """Is a 9am start's bundle due, when it is `hour:minute` in `tz`?"""
    from zoneinfo import ZoneInfo
    when = dt.datetime(2026, 11, 24, hour, minute, tzinfo=ZoneInfo(tz))
    due, not_yet, no_time = roster.due_now([_C("Ada", start_time)], now=when)
    return bool(due)


def test_a_nine_am_start_is_due_at_half_eight():
    assert _due_at(8, 31, "America/Chicago") is True
    assert _due_at(8, 29, "America/Chicago") is False


def test_a_west_coast_office_is_not_sent_three_hours_early(monkeypatch):
    """THE BUG THIS FIXES, and it fails EARLY -- a contract landing before
    anybody is in the room. 8:31am Central is 5:31am in Los Angeles, which is
    three hours before a 9am start's bundle is due there."""
    monkeypatch.setattr(C, "office_tz", lambda key="": "America/Los_Angeles")
    from zoneinfo import ZoneInfo
    central_half_eight = dt.datetime(2026, 11, 24, 8, 31,
                                     tzinfo=ZoneInfo("America/Chicago"))
    due, _n, _t = roster.due_now([_C("Ada", "9:00")],
                                 now=central_half_eight, office_key="west")
    assert due == [], "it is 5:31am where they are"

    la_half_eight = dt.datetime(2026, 11, 24, 8, 31,
                                tzinfo=ZoneInfo("America/Los_Angeles"))
    due, _n, _t = roster.due_now([_C("Ada", "9:00")],
                                 now=la_half_eight, office_key="west")
    assert [c.name for c in due] == ["Ada"]


def test_no_office_key_is_machine_local_exactly_as_before():
    """Every existing caller keeps the behaviour it has had since August."""
    naive = dt.datetime(2026, 11, 24, 8, 31)
    due, _n, _t = roster.due_now([_C("Ada", "9:00")], now=naive)
    assert [c.name for c in due] == ["Ada"]


def test_an_unreadable_start_time_is_never_sent_on_a_guess():
    due, not_yet, no_time = roster.due_now([_C("Ada", "")],
                                           now=dt.datetime(2026, 11, 24, 23, 0))
    assert due == [] and not_yet == []
    assert [c.name for c in no_time] == ["Ada"]


# ------------------------------------------- the form asks for it, 2026-11-24

def test_the_form_asks_the_question():
    """The zone was read from a column nothing wrote, so every office fell
    back to Central until somebody filled it in by hand. That was my own loose
    end from the morning's change."""
    from automations.eco_onboarding import settings as ES
    assert ES.COL_TIME_ZONE == C.TZ_COLUMN
    assert any(q.column == ES.COL_TIME_ZONE for q in ES.ALL)
    assert ES.COL_TIME_ZONE in ES.columns_needed()


def test_the_question_is_required():
    """A blank zone is the Central fallback, which is the bug -- it looks like
    an answer and is not one."""
    from automations.eco_onboarding import settings as ES
    q = next(q for q in ES.ALL if q.column == ES.COL_TIME_ZONE)
    assert q.required is True


def test_arizona_has_its_own_entry():
    """It does not change twice a year, so "Mountain" would be wrong for half
    of it -- and wrong by an hour on every send."""
    from automations.eco_onboarding import settings as ES
    assert ES.zone_name("Mountain") == "America/Denver"
    assert ES.zone_name("Mountain — Arizona (no daylight saving)") \
        == "America/Phoenix"


def test_the_sheet_holds_the_ZONE_not_the_word():
    """"Pacific" means nothing to a clock; the zone name is what handles its
    own daylight saving, and storing it means no reader needs the mapping."""
    from automations.eco_onboarding import settings as ES
    row = ES.row_for({"time_zone": "Pacific"}, "me", "now")
    assert row[ES.COL_TIME_ZONE] == "America/Los_Angeles"


def test_a_word_nobody_recognises_is_not_silently_dropped():
    """Left as typed, so it is visible on the tab rather than absent."""
    from automations.eco_onboarding import settings as ES
    row = ES.row_for({"time_zone": "somewhere else"}, "me", "now")
    assert row[ES.COL_TIME_ZONE] == "somewhere else"
    assert ES.zone_name("somewhere else") == ""


def test_the_reader_takes_either_shape(monkeypatch):
    """A cell filled in by hand before the question existed holds the word; a
    reader that understood only one of the two would quietly fall back to
    Central for the other."""
    from automations.eco_onboarding import store
    monkeypatch.setattr(store, "read",
                        lambda k, book=None: {C.TZ_COLUMN: "Pacific"})
    assert C.office_tz("x") == "America/Los_Angeles"
    monkeypatch.setattr(store, "read",
                        lambda k, book=None: {C.TZ_COLUMN: "America/Phoenix"})
    assert C.office_tz("x") == "America/Phoenix"


def test_the_zone_is_not_guessed_from_the_state():
    """Six states are split across two zones, and the office has already given
    a state -- so guessing would look reasonable and be wrong for them."""
    import inspect
    from automations.eco_onboarding import settings as ES
    src = inspect.getsource(ES)
    at = src.index("COL_TIME_ZONE = ")
    note = src[max(0, at - 1200):at]
    assert "NOT GUESSED FROM THE STATE" in note
