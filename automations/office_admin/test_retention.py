"""The Retention Report reader — the parts that do not need a browser."""
from __future__ import annotations

import datetime as dt

import pytest

from automations.office_admin import fdot, retention as R


# --------------------------------------------------------- the people it makes

def _row(first, last, email="", phone="", **extra):
    out = {"First Name": first, "Last Name": last, "Email": email,
           "Phone": phone, "Rating": "3", "Job Board": "Indeed"}
    out.update(extra)
    return out


def test_it_returns_exactly_what_the_calendar_walk_returns():
    """The seed does not know which reader filled it, so the two have to agree
    on the SHAPE as well as the people. The day they differ is the day one of
    them starts seeding a different person."""
    mine = R._as_people([_row("Ada", "Fournier", "ada@example.com", "(469) 350-6078")])
    theirs = fdot.showed_up([{"first": "Ada", "last": "Fournier",
                              "email": "ada@example.com", "phone": "(469) 350-6078",
                              "show": "Yes", "section": fdot.SECTION}])
    assert mine == theirs


def test_the_phone_is_digits_only_and_the_last_ten():
    got = R._as_people([_row("Ada", "F", phone="+1 (469) 350-6078")])
    assert got[0]["phone"] == "4693506078"


def test_somebody_listed_twice_is_one_person():
    got = R._as_people([_row("Ada", "F", "ada@example.com"),
                        _row("Ada", "F", "ADA@example.com")])
    assert len(got) == 1


def test_two_people_with_no_email_are_told_apart_by_name_and_phone():
    got = R._as_people([_row("Ada", "F", phone="4690000001"),
                        _row("Ada", "F", phone="4690000002")])
    assert len(got) == 2


def test_a_row_with_no_first_name_is_not_a_person():
    assert R._as_people([_row("", "Fournier", "x@example.com")]) == []


# ------------------------------------------------------------ the week it asks

def test_retargeting_moves_both_dates_together():
    """A href with a start from one week and an end from another returns a
    mixture, and nothing downstream could tell."""
    href = ("index.cfm?p=715&rqst=TOK&count=0&dt=11/08/2026&dt2=11/14/2026"
            "&accId=5046&id=Hired_Showed_Up")
    got = R._retarget(href, dt.date(2026, 11, 1))
    assert "dt=11/01/2026" in got and "dt2=11/07/2026" in got
    assert "11/08/2026" not in got and "11/14/2026" not in got


def test_retargeting_asks_for_sunday_through_saturday():
    got = R._retarget("x?dt=A&dt2=B", dt.date(2026, 11, 8))
    assert "dt=11/08/2026" in got and "dt2=11/14/2026" in got


def test_nothing_else_in_the_url_is_touched():
    href = "index.cfm?p=715&rqst=TOK&dt=A&dt2=B&accId=5046&id=Hired_Showed_Up"
    got = R._retarget(href, dt.date(2026, 11, 1))
    for keep in ("p=715", "rqst=TOK", "accId=5046", "id=Hired_Showed_Up"):
        assert keep in got


# ------------------------------------------------- what it refuses to guess at

class FakePage:
    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, *a, **k):
        return self.payload


class FakeApp:
    def __init__(self, payload):
        self.page = FakePage(payload)


def test_a_renamed_column_is_a_refusal_not_a_position_guess():
    """This table has already gained a column (Rating) the older detail tables
    do not have. Reading by position would have shifted every field after it
    onto the wrong one, silently."""
    app = FakeApp({"head": ["", "First", "Last Name", "Email", "Phone", ""],
                   "rows": [], "banner": ""})
    with pytest.raises(RuntimeError, match="First Name"):
        R._detail_rows(app)


def test_a_page_with_no_table_raises_rather_than_reading_empty():
    """An unread week must never seed as a week where nobody showed up."""
    with pytest.raises(RuntimeError):
        R._detail_rows(FakeApp(None))


def test_the_row_it_looks_for_is_the_new_starts_one():
    assert R.ROW_LABEL == "New Starts Showed Up"
    assert R.ROW_ID == "Hired_Showed_Up"


# ------------------------------------------- the row the BOARD is seeded from

WEEK = dt.date(2026, 11, 8)


def test_the_board_is_seeded_from_who_is_scheduled_not_who_showed_up():
    """Megan, 2026-11-15: a BOB on Monday can have a start date a fortnight
    out, and the board's week is the week somebody actually starts in the
    office. Seeded from the showed-up row, a row only appeared the morning
    they walked in — too late to onboard anybody from."""
    assert R.SCHEDULED_ROW_LABEL == "Total New Starts Scheduled"
    assert R.SCHEDULED_ROW_LABEL != R.ROW_LABEL


def test_a_scheduled_person_carries_the_day_they_are_due():
    got = R._as_people(
        [_row("Ada", "Fournier", "a@f.com", "(555) 111-2222",
              **{"Date and Time": "11/10/2026 9:00 AM"})],
        stage=R.SCHEDULED_STAGE, week_start=WEEK, dated=True)
    assert got[0]["started"] == dt.date(2026, 11, 10)
    assert got[0]["stage"] == R.SCHEDULED_STAGE


def test_an_unreadable_day_falls_back_to_the_week_and_never_invents_one():
    """A wrong Start on a row somebody onboards from is worse than a vague
    one. No `started` means board.seed_rows uses the week's Sunday, which is
    what every retention-seeded row already carries."""
    got = R._as_people(
        [_row("Ada", "Fournier", **{"Date and Time": "n/a"}),
         _row("Bruno", "Castell", **{"Date and Time": ""})],
        stage=R.SCHEDULED_STAGE, week_start=WEEK, dated=True)
    assert all("started" not in p for p in got), got


def test_a_day_outside_the_week_is_not_taken():
    """A date that is not a day of the week asked for means the page was not
    answering the question it was asked."""
    assert R._day("11/30/2026", WEEK) is None
    assert R._day("11/07/2026", WEEK) is None        # the Saturday before
    assert R._day("11/08/2026", WEEK) == WEEK        # the Sunday itself
    assert R._day("11/14/2026", WEEK) == dt.date(2026, 11, 14)


def test_a_scheduled_read_insists_on_the_date_column():
    """It is the Start on every row it makes. A table without it is the wrong
    page, and guessing a position is what the Rating column already punished."""
    app = FakeApp({"head": ["First Name", "Last Name", "Email", "Phone"],
                   "rows": [], "banner": ""})
    with pytest.raises(RuntimeError, match="Date and Time"):
        R._detail_rows(app, R.WANT + (R.DATE_COLUMN,))
    # ...and the showed-up read, which does not use it, still reads fine.
    assert R._detail_rows(app) == []


def test_the_scheduled_read_is_not_the_showed_up_read_with_a_flag():
    """They answer different questions, so one standing in for the other
    seeds a different set of people. The labels must reach the page."""
    import inspect
    src = inspect.getsource(R.read_scheduled_week)
    code = [l for l in src.splitlines() if not l.strip().startswith("#")]
    joined = "\n".join(code)
    assert "SCHEDULED_ROW_LABEL" in joined
    assert "dated=True" in joined


# ------------------------------------------- several rows, one report load

class _FakePage:
    def __init__(self, hrefs, shown):
        self.hrefs, self.shown = hrefs, shown

    def evaluate(self, js, label=None):
        if label is not None:                        # _week_href
            return self.hrefs.get(label)
        return self.shown.strftime("%m/%d/%Y") + " " + self.shown.strftime("%m/%d/%Y")


class _FakeApp:
    def __init__(self, hrefs, shown):
        self.page = _FakePage(hrefs, shown)
        self.opens, self.visited = 0, []

    def open_retention_details(self):
        self.opens += 1

    def _goto_detail(self, href):
        self.visited.append(href)


def test_read_weeks_opens_the_report_once_for_every_row_and_week(monkeypatch):
    """11/23-11/25 the 2nd-round audit re-opened the report for every (row,
    week) -- 30 loads an office -- and was killed at its timeout every day."""
    shown = dt.date(2026, 11, 22)
    href = "detail.cfm?id=X&dt=11/22/2026&dt2=11/28/2026"
    app = _FakeApp({"A": href, "B": href.replace("X", "Y")}, shown)
    monkeypatch.setattr(R, "_detail_rows", lambda app, want: [_row("Ada", "F", "a@x.com")])
    weeks = [dt.date(2026, 11, 15), shown]
    got = R.read_weeks(app, "11280", ["A", "B", "Missing"], weeks, log=lambda *a: None)
    assert app.opens == 1
    assert len(app.visited) == 4
    assert "dt=11/15/2026&dt2=11/21/2026" in app.visited[0]
    assert app.visited[1] == href                     # the shown week is not rebuilt
    assert got["Missing"] is None                     # unread, never "empty"
    assert [p["first_name"] for p in got["A"][shown]] == ["Ada"]
