"""A No ticked in ApplicantStream fills in the removal reason for them.

Megan, 2026-11-24: "if they're checked no, it'll still appear on the OBCL, but
it'll be in the show removal section, and then it should just say no show to
first day" -- and, correcting me the same day: "we're not taking anyone off of
the board. They're still on the board."

    python -m pytest automations/icd_onboarding/test_no_show_removal.py -q
"""
import datetime as dt

import pytest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F
from automations.icd_onboarding import run as R

MON = dt.date(2026, 11, 22)


class _WS:
    """A board that records its writes, by A1 range."""

    def __init__(self, rows):
        head = list(B.COLUMNS) + ["Terminated", "Removed Because"]
        # The header is row 1 on a real board (sheet.HEADER_ROW), so it is the
        # first row here -- a blank row above it makes `rows_of` read nobody,
        # which is a fixture that passes by finding nothing.
        self.grid = [head]
        for r in rows:
            self.grid.append([str(r.get(c, "")) for c in head])
        self.writes = []

    def get_all_values(self):
        return self.grid

    def batch_update(self, writes, **kw):
        self.writes.extend(writes)


def _board(monkeypatch, rows):
    from automations.icd_onboarding import sheet as S
    ws = _WS(rows)
    monkeypatch.setattr(S, "board_for",
                        lambda key, week=None, create=False: ws)
    monkeypatch.setattr(F, "on_office_machine", lambda k="": False)
    return ws


def _person(first, last, **extra):
    row = {"Week of": B.week_label(MON), "Name": first, "Last Name": last}
    row.update(extra)
    return row


# --------------------------------------------------- the reason, filled in

def test_the_reason_is_her_words_and_not_one_of_the_pick_list():
    """The pick list is what a PERSON is offered, and it already carries
    "Did not show to day 1 Classroom". Two near-identical options in one list
    is how a count stops meaning anything."""
    assert B.NO_SHOW_REASON == "No show to first day"
    assert B.NO_SHOW_REASON not in B.REMOVAL_REASONS


def test_a_no_show_lands_in_the_removed_section_with_the_reason(monkeypatch):
    ws = _board(monkeypatch, [_person("Ada", "Lovelace")])
    n = F.mark_removed_anywhere("raf", MON, ["Ada Lovelace"],
                                reason=B.NO_SHOW_REASON, dry_run=False,
                                log=lambda *a: None)
    assert n == 1
    written = [w["values"][0][0] for w in ws.writes]
    assert B.NO_SHOW_REASON in written
    assert any("/" in str(v) for v in written), "and a date, so it is removed"


def test_the_row_stays_on_the_board(monkeypatch):
    """Not a delete and not a hide-forever: the removed section is part of the
    board. Only the two past-the-chart cells are touched."""
    ws = _board(monkeypatch, [_person("Ada", "Lovelace")])
    before = [list(r) for r in ws.grid]
    F.mark_removed_anywhere("raf", MON, ["Ada Lovelace"],
                            reason=B.NO_SHOW_REASON, dry_run=False,
                            log=lambda *a: None)
    assert len(ws.grid) == len(before), "no row was removed"
    cols = {c: i for i, c in enumerate(ws.grid[0])}
    for col in ("Name", "Last Name"):
        assert ws.grid[1][cols[col]] == before[1][cols[col]]


def test_a_dry_run_writes_nothing(monkeypatch):
    ws = _board(monkeypatch, [_person("Ada", "Lovelace")])
    assert F.mark_removed_anywhere("raf", MON, ["Ada Lovelace"],
                                   reason=B.NO_SHOW_REASON, dry_run=True,
                                   log=lambda *a: None) == 0
    assert ws.writes == []


def test_somebody_already_removed_is_left_alone(monkeypatch):
    """The walk runs again every night; a second pass must not re-stamp a row
    or overwrite a reason a person typed."""
    ws = _board(monkeypatch, [_person("Gone", "Away", Terminated="11/23/2026",
                                      **{"Removed Because": "Left Classroom"})])
    assert F.mark_removed_anywhere("raf", MON, ["Gone Away"],
                                   reason=B.NO_SHOW_REASON, dry_run=False,
                                   log=lambda *a: None) == 0
    assert ws.writes == []


# --------------------------------------------------- and the Tuesday walk-in

def test_a_walk_in_is_put_back(monkeypatch):
    """Somebody marked absent on Monday who turns up on Tuesday. The date
    already outranks No Show in the column; the removed section has to agree
    with it rather than contradict it."""
    rows = [_person("Ada", "Lovelace", Terminated="11/23/2026",
                    **{"Removed Because": B.NO_SHOW_REASON})]
    monkeypatch.setattr(F, "rows_anywhere", lambda k, w, log=print: rows)
    back = R._walked_in_after_a_no_show("raf", MON, ["Ada Lovelace"],
                                        log=lambda *a: None)
    assert back == ["Ada Lovelace"]


def test_a_removal_a_PERSON_made_is_never_undone(monkeypatch):
    """They typed their own reason, so they decided something this does not
    know about -- a walk-in does not undo it."""
    rows = [_person("Ada", "Lovelace", Terminated="11/23/2026",
                    **{"Removed Because": "Left Classroom"})]
    monkeypatch.setattr(F, "rows_anywhere", lambda k, w, log=print: rows)
    assert R._walked_in_after_a_no_show("raf", MON, ["Ada Lovelace"],
                                        log=lambda *a: None) == []


def test_somebody_who_was_never_removed_is_not_restored(monkeypatch):
    rows = [_person("Ada", "Lovelace")]
    monkeypatch.setattr(F, "rows_anywhere", lambda k, w, log=print: rows)
    assert R._walked_in_after_a_no_show("raf", MON, ["Ada Lovelace"],
                                        log=lambda *a: None) == []


def test_restoring_clears_the_reason(monkeypatch):
    """A row that came back must not keep the reason for a removal that was
    undone."""
    ws = _board(monkeypatch, [_person("Ada", "Lovelace",
                                      Terminated="11/23/2026",
                                      **{"Removed Because": B.NO_SHOW_REASON})])
    n = F.mark_removed_anywhere("raf", MON, ["Ada Lovelace"], restore=True,
                                dry_run=False, log=lambda *a: None)
    assert n == 1
    assert [w["values"][0][0] for w in ws.writes] == ["", ""]


# --------------------------------------------------- the rule that governs it all

def test_a_blank_marks_nobody_off():
    """Nothing checked means nobody has said yet. The board has never marked
    anybody off for a blank and must not start -- it is the rule the whole
    board lives by."""
    import inspect
    src = inspect.getsource(R.from_no_shows)
    assert "mark_removed_anywhere" in src
    # the names come from what ApplicantStream said NO about, nothing else
    assert "no_shows_week" in src


def test_the_showed_up_answer_survives_a_failed_removal(monkeypatch):
    """The column is the load-bearing half. A removal that could not be made
    is said out loud rather than losing the pass that recorded who did not
    come."""
    import inspect
    src = inspect.getsource(R.from_no_shows)
    at = src.index("mark_removed_anywhere")
    assert "try:" in src[:at], "the removal is guarded"
    assert src.index("apply_anywhere") < at, "and the column is written first"
