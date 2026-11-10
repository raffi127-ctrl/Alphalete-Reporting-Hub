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
