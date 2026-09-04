"""The selection rule, on a board built to break it.

The whole report turns on one question -- is this person still with us? -- and
getting it wrong costs a real person a payroll record or puts one there for
somebody who left on Tuesday. So the cases here are the ones the live board
actually produced on WE 9.6, plus the shapes that would silently break a
positional reader.
"""
from __future__ import annotations

import pytest

from automations.apex_new_starts import board as BRD

# A miniature tab with the same SHAPE as the real one: row 1 carries the
# roster's per-rep titles and its MON..SUN day blocks, then the roster, then the
# 'New Starts/Raf' label, its own weekday header, a 'Roll Call' sub-header, and
# the box rows. Column positions here are nothing like the live board's on
# purpose -- if anything reads by index instead of by label, these tests fail.
def _grid():
    width = 40
    def row(pairs):
        r = [""] * width
        for c, v in pairs.items():
            r[c - 1] = v
        return r

    g = []
    # row 1: per-rep column titles + the roster's day blocks (4 wide here)
    g.append(row({6: "Start Date", 7: "# Days Worked", 8: "Termination Date",
                  10: "MON", 14: "TUES", 18: "WED", 22: "THURS", 26: "FRI",
                  30: "SAT", 34: "SUN"}))
    g.append(row({2: "#", 3: "WE 8/31- 9/6"}))            # roster header
    for i, name in enumerate(["Tenured One", "Tenured Two", "Tenured Three",
                              "Tenured Four", "Tenured Five"]):
        g.append(row({2: str(i + 1), 3: name}))
    g.append(row({3: "New Starts/Raf"}))                   # box label
    g.append(row({3: "Classroom", 4: "Trainers", 5: "Email", 9: "Location",
                  11: "Team", 12: "Monday", 16: "Tuesday", 20: "Wednesday",
                  24: "Thursday", 28: "Friday", 32: "Saturday",
                  36: "Reason Lost "}))
    g.append(row({12: "Roll Call", 16: "Roll Call", 20: "Roll Call",
                  24: "Roll Call", 28: "Roll Call", 32: "Roll Call"}))
    return g, row


def _people(rows):
    g, row = _grid()
    g.extend(row(r) for r in rows)
    return BRD.read_box(g, "Sales Board WE 9.6")


DAYS = {0: 12, 1: 16, 2: 20, 3: 24, 4: 28, 5: 32}


def _person(name, roll, extra=None):
    r = {3: name}
    r.update({DAYS[d]: v for d, v in roll.items()})
    r.update(extra or {})
    return r


def test_working_new_start_is_added():
    people = _people([_person("Caitlin Jeter",
                              {0: "CR", 1: "Hwk1C", 2: "Here", 3: "Here"},
                              {4: "Nima Aweida", 9: "Midlothian"})])
    add, skipped = BRD.to_add(people)
    assert [p.name for p in add] == ["Caitlin Jeter"]
    assert not skipped
    assert add[0].trainer == "Nima Aweida"
    assert add[0].location == "Midlothian"


def test_terminated_anywhere_in_the_week_is_skipped():
    """The rule is 'terminated ANYWHERE in the week', not 'terminated today' --
    somebody who went on Tuesday still reads Terminated on Thursday, and
    somebody terminated on Saturday must not be added on Friday either."""
    people = _people([
        _person("Gone Tuesday", {0: "CR", 1: "Terminated", 2: "Terminated"}),
        _person("Gone Saturday", {0: "CR", 1: "Here", 5: "Terminated"}),
    ])
    add, skipped = BRD.to_add(people)
    assert not add
    assert [why for _, why in skipped] == ["terminated Tuesday",
                                           "terminated Saturday"]


def test_ona_is_not_a_termination():
    """Megan, 2026-09-03: O-NA is off/NA -- 'more than likely terminated but
    isn't 100% yet'. So they are added, and flagged so a human looks."""
    people = _people([_person("Winnisha Higgins",
                              {0: "CR", 1: "Hwk1C", 2: "Off", 3: "O-NA"})])
    add, _ = BRD.to_add(people)
    assert [p.name for p in add] == ["Winnisha Higgins"]
    assert add[0].ona is True
    assert add[0].terminated is False


def test_skip_ona_holds_them_back():
    people = _people([_person("Winnisha Higgins", {0: "CR", 3: "O-NA"})])
    add, skipped = BRD.to_add(people, include_ona=False)
    assert not add
    assert "O-NA" in skipped[0][1]


def test_ona_and_terminated_reads_as_terminated():
    """A week that holds both marks is a termination. O-NA on Wednesday and
    Terminated on Thursday is somebody who went."""
    people = _people([_person("Both Marks", {2: "O-NA", 3: "Terminated"})])
    add, skipped = BRD.to_add(people)
    assert not add and skipped[0][1] == "terminated Thursday"


def test_the_box_ends_at_the_first_blank_name():
    """Below the box sits 'Leadership Promotions from this week'. Reading past
    the blank row would add a section heading to payroll."""
    g, row = _grid()
    g.append(row(_person("Real Person", {0: "CR"})))
    g.append(row({}))
    g.append(row({3: "Leadership Promotions from this week"}))
    g.append(row({3: "Somebody Promoted"}))
    people = BRD.read_box(g, "t")
    assert [p.name for p in people] == ["Real Person"]


def test_case_and_spacing_dont_matter():
    people = _people([_person("Loud Exit", {1: "  TERMINATED  "})])
    assert people[0].terminated is True


def test_missing_weekday_columns_is_a_refusal_not_an_empty_week():
    """Without the day columns every single person reads as 'not terminated'.
    That must raise, not quietly return the whole box."""
    g, row = _grid()
    # blank out the box's weekday header row
    g[8] = [""] * len(g[8])
    g[8][3 - 1] = "Classroom"
    g.append(row(_person("Anyone", {0: "CR"})))
    with pytest.raises(Exception):
        BRD.read_box(g, "t")


def test_the_hire_date_is_the_classroom_day_not_just_monday():
    """Megan, 2026-09-03: the hire date is where they're marked CR. Usually
    that IS Monday, but a late add starts mid-week and their record has to say
    the day they actually started."""
    import datetime as dt
    people = _people([
        _person("Started Monday", {0: "CR", 1: "Hwk1C", 2: "Here"}),
        _person("Added Wednesday", {2: "CR", 3: "Here"}),
    ])
    for p in people:
        p.week_start = dt.date(2026, 8, 31)      # Monday of WE 9.6
    assert people[0].hire_date == dt.date(2026, 8, 31)
    assert people[1].hire_date == dt.date(2026, 9, 2)


def test_no_classroom_day_means_no_hire_date_not_a_guess():
    """Someone carried over from an earlier cohort has no CR this week. A
    made-up hire date is a wrong number on a payroll record that nobody would
    ever catch."""
    import datetime as dt
    people = _people([_person("Carried Over", {0: "Here", 1: "Here"})])
    people[0].week_start = dt.date(2026, 8, 31)
    assert people[0].hire_date is None


def test_the_week_monday_comes_off_the_tab_name():
    import datetime as dt
    assert BRD.tab_monday("Sales Board WE 9.6",
                          dt.date(2026, 9, 3)) == dt.date(2026, 8, 31)
    assert BRD.tab_monday("not a week tab") is None
