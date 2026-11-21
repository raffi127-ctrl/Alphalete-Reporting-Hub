"""Who gets a Blue Ink reminder, and who must never get one.

python -m pytest automations/blueink_docs/test_chase.py
"""
from __future__ import annotations

import datetime as dt

from automations.blueink_docs import chase as C

START = dt.date(2026, 11, 23)


class _P:
    def __init__(self, email, first="Jaime", last="Molina"):
        self.email = email
        self.first = first
        self.last = last


def _sent(email, bundle="B1", note=""):
    # ledger.row_for shape: sent_at, tab, name, email, bundle, status,
    # checked, note
    return ["11/20/2026", "D2D OBCL 11.23", "Jaime Molina", email, bundle,
            "sent", "11/20/2026", note]


class TestWhichDay:
    def test_only_the_day_before_and_the_morning_of(self):
        assert C.due_kind(START, dt.date(2026, 11, 22)) == C.DAY_BEFORE
        assert C.due_kind(START, dt.date(2026, 11, 23)) == C.MORNING_OF

    def test_not_every_day_in_between(self):
        # a packet outstanding for a week would otherwise be chased every
        # morning, which teaches people to ignore the one that matters
        assert C.due_kind(START, dt.date(2026, 11, 19)) is None
        assert C.due_kind(START, dt.date(2026, 11, 21)) is None

    def test_not_after_they_have_started(self):
        assert C.due_kind(START, dt.date(2026, 11, 24)) is None

    def test_no_start_date_is_no_chase(self):
        assert C.due_kind(None, dt.date(2026, 11, 22)) is None


class TestWhoIsDue:
    def _starts(self, email):
        return {email: START}

    def test_somebody_we_sent_to_is_chased(self):
        p = _P("a@x.com")
        got = C.plan([p], [_sent("a@x.com")], self._starts("a@x.com"),
                     dt.date(2026, 11, 22))
        assert [(x[1], x[2]) for x in got] == [("B1", C.DAY_BEFORE)]

    def test_never_sent_is_never_chased(self):
        """A reminder for a contract nobody has is a confusing email."""
        p = _P("b@x.com")
        assert C.plan([p], [], self._starts("b@x.com"),
                      dt.date(2026, 11, 22)) == []

    def test_the_same_chase_does_not_go_twice(self):
        p = _P("a@x.com")
        rows = [_sent("a@x.com"),
                _sent("a@x.com", note=C.note_for(C.DAY_BEFORE, START))]
        assert C.plan([p], rows, self._starts("a@x.com"),
                      dt.date(2026, 11, 22)) == []

    def test_the_morning_of_still_goes_after_the_day_before(self):
        p = _P("a@x.com")
        rows = [_sent("a@x.com"),
                _sent("a@x.com", note=C.note_for(C.DAY_BEFORE, START))]
        got = C.plan([p], rows, self._starts("a@x.com"),
                     dt.date(2026, 11, 23))
        assert [x[2] for x in got] == [C.MORNING_OF]

    def test_a_moved_start_gets_the_new_days_chases(self):
        """Keyed on the start date too, so a reschedule is chased afresh
        without the old day's reminder going twice."""
        p = _P("a@x.com")
        rows = [_sent("a@x.com"),
                _sent("a@x.com", note=C.note_for(C.DAY_BEFORE, START))]
        moved = dt.date(2026, 11, 30)
        got = C.plan([p], rows, {"a@x.com": moved}, dt.date(2026, 11, 29))
        assert [x[2] for x in got] == [C.DAY_BEFORE]

    def test_no_email_no_chase(self):
        assert C.plan([_P("")], [_sent("")], {}, dt.date(2026, 11, 22)) == []
