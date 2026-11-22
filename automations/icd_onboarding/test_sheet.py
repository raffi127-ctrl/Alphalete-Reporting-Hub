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

SUNDAY = dt.date(2026, 11, 8)   # the board's week starts on a Sunday
MONDAY = SUNDAY                # older name, same week
HEAD = list(B.COLUMNS) + list(S.PAST_THE_CHART)


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
    assert weeks == ["11/15/2026", "11/08/2026"]


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


# ------------------------------------- a status advances; a tick does not

def test_a_status_may_advance_over_itself():
    """Sent -> Passed has to land, or the board freezes at whatever arrived
    first (Megan, 2026-11-09)."""
    ws = FakeWS([_person("Ada Fournier", **{"BG Status": "Sent"})])
    n = S.write_step(FakeBook(ws), MONDAY, "BG Status",
                     {"Ada Fournier": "Passed"}, log=lambda *a: None)
    assert n == 1
    assert "Passed" in str(ws.updates)


def test_a_status_never_goes_backwards():
    """A late 'Sent' email must not pull somebody back from Passed."""
    ws = FakeWS([_person("Ada Fournier", **{"BG Status": "Passed"})])
    assert S.write_step(FakeBook(ws), MONDAY, "BG Status",
                        {"Ada Fournier": "Sent"}, log=lambda *a: None) == 0
    assert ws.updates == []


def test_an_ordinary_tick_is_still_written_once():
    ws = FakeWS([_person("Ada Fournier", **{"Blue Ink": "11/03/2026"})])
    assert S.write_step(FakeBook(ws), MONDAY, "Blue Ink",
                        {"Ada Fournier": "11/09/2026"}, log=lambda *a: None) == 0


def test_a_status_lands_on_an_empty_cell():
    ws = FakeWS([_person("Ada Fournier")])
    assert S.write_step(FakeBook(ws), MONDAY, "BG Status",
                        {"Ada Fournier": "Sent"}, log=lambda *a: None) == 1


def test_write_step_refuses_a_column_no_machine_owns():
    ws = FakeWS([_person("Ada Fournier")])
    with pytest.raises(ValueError):
        S.write_step(FakeBook(ws), MONDAY, B.CLASSROOM,
                     {"Ada Fournier": "Tuesday AM"}, log=lambda *a: None)


# ------------------- a new column has to reach boards that already exist

class _FakeWS:
    def __init__(self, head):
        self.grid = [list(head)]
        self.updates = []

    def get_all_values(self):
        return self.grid

    def update(self, values=None, range_name=None):
        self.updates.append((range_name, values))


def test_a_missing_column_is_appended(monkeypatch):
    """open_board never re-lays an existing tab, so a column added to
    B.COLUMNS would only ever reach boards made afterwards."""
    head = ([c for c in B.COLUMNS if c != B.GENDER]
            + list(S.PAST_THE_CHART))
    ws = _FakeWS(head)
    got = S.ensure_columns(ws, log=lambda *a: None)
    assert got == [B.GENDER]
    (where, values), = ws.updates
    assert values == [[B.GENDER]]
    # appended to the RIGHT of everything already there, row 1
    assert where == "%s%d" % (S._a1(len(head) + 1), S.HEADER_ROW)


class _NarrowWS(_FakeWS):
    """A sheet at its column limit, the way a real one reports itself."""

    def __init__(self, head, col_count=None):
        super().__init__(head)
        self.col_count = len(head) if col_count is None else col_count
        self.grown = []

    def add_cols(self, n):
        self.grown.append(n)
        self.col_count += n


def test_the_grid_is_widened_before_the_header_is_written():
    """A Sheet has a fixed column count and a write one cell past it is
    REFUSED -- "Range (Onboarding!W1) exceeds grid limits. Max columns: 22".
    Both callers swallow that into a one-line log of the exception type, so
    for every board already at its limit the column silently never appeared
    (2026-11-20, `Funnel`)."""
    head = [c for c in B.COLUMNS if c != B.GENDER] + list(S.PAST_THE_CHART)
    ws = _NarrowWS(head)
    assert S.ensure_columns(ws, log=lambda *a: None) == [B.GENDER]
    assert ws.grown == [1], "the grid has to grow by exactly what is missing"
    assert ws.col_count == len(head) + 1
    # and only then is the header written
    (where, _), = ws.updates
    assert where == "%s%d" % (S._a1(len(head) + 1), S.HEADER_ROW)


def test_a_wide_enough_grid_is_not_grown():
    head = [c for c in B.COLUMNS if c != B.GENDER] + list(S.PAST_THE_CHART)
    ws = _NarrowWS(head, col_count=len(head) + 10)
    S.ensure_columns(ws, log=lambda *a: None)
    assert ws.grown == []


def test_nothing_is_moved_or_removed(monkeypatch):
    """Somebody may have added a column of their own."""
    head = list(B.COLUMNS) + list(S.PAST_THE_CHART) + ["Megan's note"]
    ws = _FakeWS(head)
    assert S.ensure_columns(ws, log=lambda *a: None) == []
    assert ws.updates == []


def test_an_empty_tab_is_left_alone():
    """A blank grid is not a board with every column missing."""
    ws = _FakeWS([])
    assert S.ensure_columns(ws, log=lambda *a: None) == []
    assert ws.updates == []


def test_ensure_columns_adds_every_column_past_the_chart():
    """`Removed Because` was laid out on NEW boards and missing from
    ensure_columns, so every board that already existed silently lacked it and
    every removal logged "reason not written". The 15 removals on the week of
    11/08 have no reason recorded because of it (2026-11-15).

    One list now, so a column cannot be in the layout and not in the repair.
    """
    import inspect
    head = inspect.getsource(S._header_block)
    fix = inspect.getsource(S.ensure_columns)
    assert "PAST_THE_CHART" in head
    assert "PAST_THE_CHART" in fix
    # and the thing that actually matters: the repair covers the layout
    laid_out = S._header_block()[0]
    for col in list(B.COLUMNS) + list(S.PAST_THE_CHART):
        assert col in laid_out, col


def test_the_removal_reason_column_is_not_a_step():
    """It is row state kept past the chart, like the Terminated date -- not a
    column anybody works through, and no source may tick it."""
    from automations.icd_onboarding import fillers as F
    assert B.REMOVED_WHY in S.PAST_THE_CHART
    assert B.REMOVED_WHY not in B.COLUMNS
    assert B.REMOVED_WHY not in B.TICKS
    for source, cols in F.SOURCES.items():
        assert B.REMOVED_WHY not in cols, source


class _DividerWS(_FakeWS):
    """A board with a Funnel column and real rows, for divider tests."""

    def __init__(self, rows):
        head = list(B.COLUMNS) + list(S.PAST_THE_CHART)
        super().__init__(head)
        self.col_count = len(head)
        self._head = head
        self.inserted = []
        self._rows = rows

    def add_cols(self, n):
        self.col_count += n

    def get_all_values(self):
        at = {c: i for i, c in enumerate(self._head)}
        out = [list(self._head)]
        for r in self._rows:
            line = [""] * len(self._head)
            for k, v in r.items():
                line[at[k]] = v
            out.append(line)
        return out

    def insert_row(self, values, index):
        self.inserted.append((index, values))


def _funnel_row(name, funnel="", week="11/15/2026"):
    return {B.WEEK: week, "Name": name, "Last Name": "X", B.FUNNEL: funnel}


class TestDividersOnAnyWeek:
    """Megan 2026-11-20: "we need it correct for every week"."""

    def test_a_week_with_no_new_people_still_gets_its_line(self):
        ws = _DividerWS([_funnel_row("A"), _funnel_row("B", "Algemar"),
                         _funnel_row("C", "Algemar")])
        assert S.ensure_dividers(ws, dt.date(2026, 11, 16),
                                 log=lambda *a: None) == 1
        (at, values), = ws.inserted
        assert at == 3, "above the first Algemar row, not the top of the week"
        assert "Algemar" in " ".join(values)

    def test_the_office_s_own_people_get_no_divider(self):
        ws = _DividerWS([_funnel_row("A"), _funnel_row("B")])
        assert S.ensure_dividers(ws, dt.date(2026, 11, 16),
                                 log=lambda *a: None) == 0
        assert ws.inserted == []

    def test_a_line_already_there_is_not_drawn_twice(self):
        existing = {B.WEEK: "11/15/2026", "Name": "", "Last Name": "",
                    B.DIVIDER_AT: B.divider_row("11/15/2026",
                                                "Algemar")[B.DIVIDER_AT]}
        ws = _DividerWS([_funnel_row("A"), existing, _funnel_row("B", "Algemar")])
        assert S.ensure_dividers(ws, dt.date(2026, 11, 16),
                                 log=lambda *a: None) == 0

    def test_scattered_rows_are_reported_not_mislabelled(self):
        """A line above the first would claim the person in between."""
        said = []
        ws = _DividerWS([_funnel_row("A", "Algemar"), _funnel_row("B"),
                         _funnel_row("C", "Algemar")])
        assert S.ensure_dividers(ws, dt.date(2026, 11, 16),
                                 log=said.append) == 0
        assert ws.inserted == []
        assert any("scattered" in m for m in said)

    def test_another_week_is_left_alone(self):
        ws = _DividerWS([_funnel_row("A", "Algemar", week="11/08/2026")])
        assert S.ensure_dividers(ws, dt.date(2026, 11, 16),
                                 log=lambda *a: None) == 0


# ------------------------- addressing the row a person is actually on

class TestRowNumbersSurviveAGap:
    """A nameless row makes rows_of SHORTER than the block it read.

    2026-11-22: every writer here addressed cells as
    `FIRST_DATA_ROW + <index into rows_of>`, which is short by one for each
    row skipped above. On Raf's stacked tab -- 97 rows, 93 returned -- it put
    two people's OwnerVille columns two rows up, onto two others. Only
    write_step's refusal to touch a non-empty cell kept it from defacing
    anything.
    """

    def _gap_grid(self):
        # Ada, a nameless spacer, then Bruno and Cara: physical rows 2, 3,
        # 4, 5 with the header on 1.
        return FakeWS([_person("Ada Fournier"),
                       [""] * len(HEAD),
                       _person("Bruno Castell"),
                       _person("Cara Dunne")])

    def test_rows_of_reports_the_row_each_person_is_on(self):
        ws = self._gap_grid()
        rows = S.rows_of(ws.get_all_values())
        assert [S.row_number(r) for r in rows] == [2, 4, 5]

    def test_the_index_would_have_said_otherwise(self):
        """The old arithmetic, kept here as the thing being prevented."""
        ws = self._gap_grid()
        rows = S.rows_of(ws.get_all_values())
        old = [S.FIRST_DATA_ROW + i for i, _ in enumerate(rows)]
        assert old == [2, 3, 4]
        assert old != [S.row_number(r) for r in rows]

    def test_write_step_writes_to_the_row_past_the_gap(self):
        ws = self._gap_grid()
        n = S.write_step(None, MONDAY, "Owner Submit",
                         {"Cara Dunne": "11/22/2026"}, ws=ws,
                         log=lambda *a: None)
        assert n == 1
        cell = ws.updates[0][0]
        assert cell.endswith("5"), "Cara is on row 5, not %s" % cell

    def test_tick_lands_past_the_gap(self):
        ws = self._gap_grid()
        S.tick(FakeBook(ws), MONDAY, "Contact Added", ["Bruno Castell"],
               log=lambda *a: None)
        assert ws.updates, "nothing was written"
        assert ws.updates[0][0].endswith("4"), ws.updates[0][0]

    def test_terminate_marks_the_right_row(self):
        ws = self._gap_grid()
        S.terminate(FakeBook(ws), MONDAY, ["Cara Dunne"], reason="No Show",
                    log=lambda *a: None)
        assert ws.updates, "nothing was written"
        assert all(r.endswith("5") for r, _ in ws.updates), ws.updates

    def test_a_hand_built_row_is_refused_not_guessed(self):
        """The failure mode being replaced always produced *a* number."""
        with pytest.raises(RuntimeError, match="which sheet row"):
            S.row_number({"Name": "Ada", "Last Name": "Fournier"})


class TestAppendingDoesNotLandOnAnybody:
    def test_the_first_free_row_is_past_every_physical_row(self):
        ws = FakeWS([_person("Ada Fournier"),
                     [""] * len(HEAD),
                     _person("Bruno Castell")])
        grid = ws.get_all_values()
        # 4 physical rows -> the next free one is 5. The old sum
        # (FIRST_DATA_ROW + 2 people) said 4, which is Bruno's own row.
        assert S.first_free_row(grid) == 5
        assert S.FIRST_DATA_ROW + len(S.rows_of(grid)) == 4

    def test_an_empty_tab_still_starts_at_the_first_data_row(self):
        assert S.first_free_row([list(HEAD)]) == S.FIRST_DATA_ROW


class TestAnAskDoesNotWedgeTheStep:
    """A NEEDS: cell is an ask, and the real date must land on top of it.

    2026-11-22: `plan` treated such a cell as outstanding and asked for the
    date, while write_step and tick_plan both read "already done" off the cell
    being non-empty -- so the write was planned and then refused, and anybody
    carrying an ask could never have that step ticked at all. The prefix was
    introduced in the first place to stop exactly that (fillers, 2026-11-15).
    """

    def _row(self, digi):
        return _person("Ada Fournier", **{"Digi Docs": digi})

    def test_board_says_an_ask_is_not_an_answer(self):
        assert not B.answered(B.ASK_PREFIX + "an email on the chart")
        assert B.answered("11/22/2026")
        assert not B.answered("")
        assert not B.answered("   ")

    def test_write_step_writes_over_an_ask(self):
        from automations.icd_onboarding import fillers as F
        ws = FakeWS([self._row(F.ALERT_PREFIX + "an email on the chart")])
        n = S.write_step(None, MONDAY, "Digi Docs",
                         {"Ada Fournier": "11/22/2026"}, ws=ws,
                         log=lambda *a: None)
        assert n == 1, "the ask wedged the step shut"
        assert ws.updates and ws.updates[0][1] == [["11/22/2026"]]

    def test_write_step_still_leaves_a_real_answer_alone(self):
        ws = FakeWS([self._row("11/01/2026")])
        n = S.write_step(None, MONDAY, "Digi Docs",
                         {"Ada Fournier": "11/22/2026"}, ws=ws,
                         log=lambda *a: None)
        assert n == 0, "a tick is written once"

    def test_tick_plan_counts_an_ask_as_outstanding(self):
        from automations.icd_onboarding import fillers as F
        rows = S.rows_of(FakeWS([
            self._row(F.ALERT_PREFIX + "an email on the chart")
        ]).get_all_values())
        assert B.tick_plan(rows, "Digi Docs", ["Ada Fournier"]) == [0]

    def test_tick_plan_still_skips_a_real_answer(self):
        rows = S.rows_of(FakeWS([self._row("11/01/2026")]).get_all_values())
        assert B.tick_plan(rows, "Digi Docs", ["Ada Fournier"]) == []

    def test_fillers_and_board_share_one_definition(self):
        """Two copies of the prefix is how the two sides drifted apart."""
        from automations.icd_onboarding import fillers as F
        assert F.ALERT_PREFIX is B.ASK_PREFIX
        assert F.is_alert is B.is_ask
