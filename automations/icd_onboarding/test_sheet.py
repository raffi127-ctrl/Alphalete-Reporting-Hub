"""The sheet half — what it writes, and the much longer list of what it won't.

A fake worksheet rather than a real one: these rules are about restraint, and
restraint is exactly what a live sheet makes expensive to test. The grid is the
same shape the real tab has (week row, header row, then people).
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import sheet as S

MONDAY = dt.date(2026, 11, 2)
HEAD = list(B.COLUMNS) + [B.TERMINATED_AT]


class FakeWS:
    def __init__(self, rows=()):
        self.title = B.TAB
        self.grid = [list(HEAD)] + [list(r) for r in rows]
        self.updates, self.formats = [], []

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def update(self, values=None, range_name=None):
        self.updates.append((range_name, values))

    def batch_update(self, items):
        self.updates.extend((i["range"], i["values"]) for i in items)

    def format(self, ranges, fmt):
        self.formats.append((ranges, fmt))

    def freeze(self, rows=None):
        pass


class FakeBook:
    def __init__(self, ws=None):
        self._ws = ws
        self.added = []

    def worksheets(self):
        return [self._ws] if self._ws else []

    def add_worksheet(self, title=None, rows=None, cols=None):
        self._ws = FakeWS()
        self._ws.title = title
        self._ws.grid = [[]]
        self.added.append(title)
        return self._ws


def _person(name, week=None, **extra):
    row = [""] * len(HEAD)
    first, last = name.split()[0], " ".join(name.split()[1:])
    row[HEAD.index(B.WEEK)] = week or B.week_label(MONDAY)
    row[HEAD.index("Name")] = first
    row[HEAD.index("Last Name")] = last
    row[HEAD.index("Email")] = first.lower() + "@example.com"
    for k, v in extra.items():
        row[HEAD.index(k)] = v
    return row


def _cal(*names):
    return [{"first_name": n.split()[0], "last_name": " ".join(n.split()[1:]),
             "email": n.split()[0].lower() + "@example.com", "phone": "5550100001"}
            for n in names]


# ------------------------------------------------------------ reading it

def test_columns_are_found_by_name_not_position():
    ws = FakeWS([_person("Ada Fournier")])
    cols = S.layout(ws.get_all_values())
    assert cols["Classroom"] == HEAD.index("Classroom")
    assert cols[B.TERMINATED_AT] == HEAD.index(B.TERMINATED_AT)


def test_blank_rows_are_not_people():
    ws = FakeWS([_person("Ada Fournier"), [""] * len(HEAD)])
    assert [r["Name"] for r in S.rows_of(ws.get_all_values())] == ["Ada"]


# -------------------------------------------------------------- seeding

def test_a_new_office_gets_one_onboarding_tab():
    book = FakeBook()
    S.seed(book, MONDAY, _cal("Ada Fournier"), log=lambda *a: None)
    assert book.added == [B.TAB], "one tab, not one per week"
    assert any(B.WEEK in str(v) for _, v in book._ws.updates)


def test_a_second_week_goes_onto_the_SAME_tab():
    """52 tabs a year in somebody's own metrics workbook is not a board,
    it is a mess (Megan, 2026-11-08: "add a tab to their metrics sheet?")."""
    ws = FakeWS([_person("Ada Fournier")])
    book = FakeBook(ws)
    later = MONDAY + dt.timedelta(days=7)
    S.seed(book, later, _cal("Bruno Castell"), log=lambda *a: None)
    assert book.added == [], "no new tab"
    written = " ".join(str(v) for _, v in ws.updates)
    assert "Bruno" in written and B.week_label(later) in written


def test_a_week_only_sees_its_own_rows():
    rows = [_person("Ada Fournier"),
            _person("Bruno Castell", week=B.week_label(MONDAY + dt.timedelta(days=7)))]
    got = B.for_week(S.rows_of(FakeWS(rows).get_all_values()), MONDAY)
    assert [r["Name"] for r in got] == ["Ada"]


def test_the_picker_is_offered_every_week_newest_first():
    rows = [_person("Ada Fournier"),
            _person("Bruno Castell", week=B.week_label(MONDAY + dt.timedelta(days=7)))]
    weeks = B.weeks_on(S.rows_of(FakeWS(rows).get_all_values()))
    assert weeks == ["11/09/2026", "11/02/2026"]


def test_seeding_twice_adds_nobody_twice():
    ws = FakeWS([_person("Ada Fournier")])
    book = FakeBook(ws)
    plan = S.seed(book, MONDAY, _cal("Ada Fournier"), log=lambda *a: None)
    assert plan["add"] == []
    assert ws.updates == [], "and writes nothing at all"


def test_a_re_seed_leaves_a_hand_set_classroom_alone():
    """Their work is worth more than a tidy re-seed."""
    ws = FakeWS([_person("Ada Fournier", Classroom="Tuesday AM")])
    book = FakeBook(ws)
    S.seed(book, MONDAY, _cal("Ada Fournier", "Bruno Castell"), log=lambda *a: None)
    written = " ".join(str(v) for _, v in ws.updates)
    assert "Bruno" in written
    assert "Tuesday AM" not in written, "it never rewrites the existing row"


def test_somebody_marked_off_is_not_re_added():
    ws = FakeWS([_person("Ada Fournier", **{B.TERMINATED_AT: "11/06/2026"})])
    book = FakeBook(ws)
    plan = S.seed(book, MONDAY, _cal("Ada Fournier"), log=lambda *a: None)
    assert plan["add"] == []


def test_a_dry_run_writes_nothing():
    ws = FakeWS([_person("Ada Fournier")])
    book = FakeBook(ws)
    S.seed(book, MONDAY, _cal("Bruno Castell"), dry_run=True, log=lambda *a: None)
    assert ws.updates == []


# --------------------------------------------------------------- ticking

def test_a_tick_writes_a_date_and_greens_the_cell():
    ws = FakeWS([_person("Ada Fournier")])
    n = S.tick(FakeBook(ws), MONDAY, "Blue Ink", ["Ada Fournier"], log=lambda *a: None)
    assert n == 1
    assert ws.formats and ws.formats[0][1]["backgroundColor"] == B.GREEN


def test_a_tick_never_lands_on_a_column_it_does_not_own():
    ws = FakeWS([_person("Ada Fournier")])
    with pytest.raises(ValueError):
        S.tick(FakeBook(ws), MONDAY, B.CLASSROOM, ["Ada Fournier"], log=lambda *a: None)


def test_an_already_ticked_cell_is_left_alone():
    ws = FakeWS([_person("Ada Fournier", **{"Blue Ink": "11/03/2026"})])
    assert S.tick(FakeBook(ws), MONDAY, "Blue Ink", ["Ada Fournier"],
                  log=lambda *a: None) == 0
    assert ws.updates == []


def test_a_renamed_column_says_so_instead_of_guessing():
    ws = FakeWS([_person("Ada Fournier")])
    ws.grid[0][HEAD.index("Blue Ink")] = "BlueInk"
    with pytest.raises(RuntimeError, match="no 'Blue Ink' column"):
        S.tick(FakeBook(ws), MONDAY, "Blue Ink", ["Ada Fournier"], log=lambda *a: None)


# ------------------------------------------------------- off, and classrooms

def test_marking_somebody_off_keeps_their_row():
    ws = FakeWS([_person("Ada Fournier"), _person("Bruno Castell")])
    n = S.terminate(FakeBook(ws), MONDAY, ["Bruno Castell"], log=lambda *a: None)
    assert n == 1
    assert len(ws.grid) == 3, "header + both people — the row is still there"
    assert all("Bruno" not in str(v) for _, v in ws.updates), "only a date is written"


def test_marking_off_twice_does_nothing_the_second_time():
    ws = FakeWS([_person("Ada Fournier", **{B.TERMINATED_AT: "11/06/2026"})])
    assert S.terminate(FakeBook(ws), MONDAY, ["Ada Fournier"],
                       log=lambda *a: None) == 0


def test_the_classroom_can_be_set_and_changed():
    ws = FakeWS([_person("Ada Fournier", Classroom="Tuesday AM")])
    book = FakeBook(ws)
    assert S.set_classroom(book, MONDAY, {"Ada Fournier": "Tuesday AM"},
                           log=lambda *a: None) == 0, "no change, no write"
    assert S.set_classroom(book, MONDAY, {"Ada Fournier": "Thursday PM"},
                           log=lambda *a: None) == 1
