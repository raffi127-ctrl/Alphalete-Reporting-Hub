"""Reading the training calendar, against the screen rebuilt from the page.

The FIRST DAY OF TRAINING table here has the SHAPE of Raf's real calendar
(office 11280, from Megan's screenshot 2026-11-06): the columns in the order
they appear, the Show Up radio pair, the Follow Up Status dropdown beside them,
and the empty FIRST DAY OF SALES banner that sits on the same page.

THE PEOPLE IN IT ARE INVENTED. The real page shows applicants -- names, mobile
numbers, personal email addresses. None of that belongs in a fixture: this repo
is public, and a test file is forever. The reader is being tested on markup, so
markup is all the fixture carries.

WHAT THIS PROVES, AND WHAT IT DOESN'T. It proves the reader picks the right
section, the right column and the right rows on a page shaped like that one. It
does NOT prove ApplicantStream's real markup nests its cells the way this
fixture does -- only a saved copy of the live page can settle that. Same caveat,
and for the same reason, as `apex_new_starts/test_form_match.py`.

The risk being guarded is specific: this list creates payroll records. A reader
that silently returns nobody, or that reads the FIRST DAY OF SALES section, or
that counts a 'Cancelled' follow-up as a no-show, puts a real person on payroll
wrongly or leaves one off it.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.office_admin import fdot

pytest.importorskip("patchright.sync_api")

STATUSES = ("Cancelled", "Confirmed", "Booked Today - Confirmed", "Called")

# (first, last, phone, email, showed, follow-up status) -- invented people, in
# the shape the page presents them. Two-word surnames and mixed-case emails are
# here because the real page has both.
ROWS = [
    ("Ada", "Fournier", "15550100001", "ada.f@example.com", False, "Cancelled"),
    ("Bruno", "Castell", "15550100002", "Bruno.C@example.com", True, "Confirmed"),
    ("Cora", "Nilsen", "15550100003", "cora@example.org", True, "Booked Today - Confirmed"),
    ("Dev", "Rao", "15550100004", "Dev.Rao@example.com", True, "Booked Today - Confirmed"),
    ("Esme", "Vance Hale", "15550100005", "esme@example.net", False, "Cancelled"),
    ("Finn", "Okelly", "15550100006", "finn@example.com", False, "Called"),
    ("Gita", "Marsh", "15550100007", "gita@example.com", False, "Called"),
    ("Hugo", "Lindqvist", "15550100008", "hugo@example.org", False, "Called"),
    ("Isla", "Pereira", "15550100009", "Isla.P@example.com", True, "Confirmed"),
    ("Jonah", "Whitfield", "15550100010", "jonah@example.net", False, "Cancelled"),
]

HEADER = ("Time", "First Name", "Last Name", "Phone", "Cell Phone", "Email",
          "Rating", "Booked By", "First By Phone", "Job Board", "Show Up",
          "Done By", "Remove", "Follow Up Status", "Follow Up By",
          "Follow Up Time")


def _row(i, first, last, phone, email, showed, status, radios=True):
    yes = " checked" if showed else ""
    no = "" if showed else " checked"
    show_cell = (
        '<input type="radio" name="su%d" value="1"%s>Yes '
        '<input type="radio" name="su%d" value="0"%s>No' % (i, yes, i, no)
    ) if radios else "&nbsp;"
    opts = "".join('<option%s>%s</option>' % (" selected" if s == status else "", s)
                   for s in STATUSES)
    return (
        "<tr><td>12:30 PM</td><td>%s</td><td>%s</td><td>%s</td><td></td>"
        "<td>%s</td><td>&#9733;&#9733;</td><td></td><td></td><td>Indeed</td>"
        "<td>%s</td><td><select><option>None</option></select></td><td></td>"
        "<td><select>%s</select></td><td>A Recruiter</td><td>Mon,02 06:3 AM</td></tr>"
        % (first, last, phone, email, show_cell, opts))


def _table(rows, radios=True):
    head = "<tr>" + "".join("<th>%s</th>" % h for h in HEADER) + "</tr>"
    body = "".join(_row(i, *r, radios=radios) for i, r in enumerate(rows))
    return head + body


def page_html(rows=ROWS, radios=True, banner=True, sales_rows=()):
    """The calendar page: an empty FIRST DAY OF SALES, then the training table."""
    if sales_rows:
        sales = ('<div class="banner">FIRST DAY OF SALES</div>'
                 '<table>%s</table>' % _table(sales_rows))
    else:
        sales = "<div>No First Day of Sales found for 11-02-2026</div>"
    head = ('<div class="banner">%s</div>' % fdot.SECTION) if banner else ""
    return ("<!doctype html><html><body>"
            "<div>An Owner | AN OFFICE, INC. | Calendars for 11-06-2026</div>"
            "<div>Office ID: 11280 Owner: An Owner</div>"
            + sales + head +
            "<table>%s</table></body></html>" % _table(rows, radios=radios))


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


def _read(pg, html=None):
    pg.set_content(html or page_html())
    return pg.evaluate(fdot.READ_JS, fdot.SECTION)


# ------------------------------------------------------------- the one rule

def test_only_the_people_marked_showed_up_come_back(page):
    got = _read(page)
    assert got["ok"] is True
    people = fdot.showed_up(got["rows"])
    assert [p["first_name"] for p in people] == ["Bruno", "Cora", "Dev", "Isla"]


def test_a_cancelled_follow_up_does_not_remove_somebody_who_showed(page):
    """Follow Up Status is the appointment, not the outcome (Megan, 11/06:
    "it's just if they are scheduled to start"). A reader that filtered on it
    would drop a person who actually started."""
    rows = [("Nadia", "Okafor", "15550109999", "nadia@example.com", True, "Cancelled")]
    people = fdot.showed_up(_read(page, page_html(rows))["rows"])
    assert [p["first_name"] for p in people] == ["Nadia"]


def test_the_email_comes_through_because_it_is_the_match_that_is_proof(page):
    people = fdot.showed_up(_read(page)["rows"])
    assert people[0]["email"] == "Bruno.C@example.com"
    assert people[0]["phone"] == "5550100002"


# --------------------------------------------------- the wrong-section trap

def test_the_first_day_of_sales_section_is_not_read(page):
    """Both sections live on the same page. Reading the wrong one would create
    payroll records for people who have not started."""
    sales = [("Wrong", "Person", "15550108888", "wrong@example.com", True, "Confirmed")]
    got = _read(page, page_html(ROWS, sales_rows=sales))
    names = [p["first_name"] for p in fdot.showed_up(got["rows"])]
    assert "Wrong" not in names
    assert names == ["Bruno", "Cora", "Dev", "Isla"]


def test_no_training_banner_is_an_error_not_an_empty_week(page):
    got = _read(page, page_html(banner=False))
    assert got["ok"] is False
    assert fdot.SECTION in got["error"]


# ----------------------------------------------- never silently return none

def test_rows_with_no_show_up_control_raise_rather_than_read_as_nobody(page):
    """The column moving is indistinguishable from nobody showing up, unless
    somebody says so out loud."""
    got = _read(page, page_html(radios=False))
    assert got["ok"] is True, "the section was found"
    assert fdot.showed_up(got["rows"]) == [], "and nobody reads as showing up"
    with pytest.raises(RuntimeError, match="Show Up control"):
        fdot.check_rows(got["rows"])


def test_a_genuinely_empty_week_is_fine(page):
    rows = [("Ada", "Fournier", "15550100001", "ada.f@example.com", False, "Cancelled")]
    got = _read(page, page_html(rows))
    fdot.check_rows(got["rows"])                 # does not raise: controls exist
    assert fdot.showed_up(got["rows"]) == []


# ------------------------------------------------------------ pooling a week

def test_someone_rescheduled_inside_the_week_is_one_person_not_two():
    """No on Monday, Yes on Wednesday. A second row would be a second payroll
    record for a real employee."""
    mon = {"first": "Bruno", "last": "Castell", "phone": "15550100002",
           "email": "bruno@example.com", "show": "Yes", "section": fdot.SECTION}
    assert len(fdot.showed_up([mon, dict(mon)])) == 1


def test_the_same_person_from_two_days_matches_on_email_not_spelling():
    """The calendar spells a name differently on two days; the email is the
    same. Email is proof, name is judgement."""
    a = {"first": "Esme", "last": "Vance Hale", "phone": "15550100005",
         "email": "esme@example.net", "show": "Yes", "section": fdot.SECTION}
    b = dict(a, last="Vance-Hale", phone="")
    assert len(fdot.showed_up([a, b])) == 1


def test_two_people_with_no_email_are_still_two_people():
    a = {"first": "Ana", "last": "Diaz", "phone": "15550100021", "email": "",
         "show": "Yes", "section": fdot.SECTION}
    b = dict(a, first="Ben", phone="15550100022")
    assert len(fdot.showed_up([a, b])) == 2


def test_a_week_reads_all_seven_days_whichever_day_it_is_given(monkeypatch):
    """Given any date in the week, it reads that whole week -- not the next
    seven days from whenever it happened to run. All seven, because a training
    day nobody expected is the one that would be missed (Megan, 11/08)."""
    seen = []

    def fake_read(app, office, day, log=print):
        seen.append(day)
        return []

    monkeypatch.setattr(fdot, "read", fake_read)
    fdot.read_week(None, "11280", dt.date(2026, 11, 6), log=lambda *a: None)
    assert seen[0] == dt.date(2026, 11, 2), "Monday of that week"
    assert seen[-1] == dt.date(2026, 11, 8), "Sunday"
    assert len(seen) == 7


def test_a_day_the_calendar_says_has_no_training_is_a_proven_zero(page):
    """Sundays, mostly. The page says so in as many words -- the same sentence
    it uses for an empty First Day of Sales -- and that sentence is the only
    thing that turns "nothing here" into a fact rather than a guess
    ([[feedback_empty_means_proven_zero]])."""
    html = ("<!doctype html><html><body>"
            "<div>No First Day of Training found for 11-08-2026</div>"
            "</body></html>")
    got = _read(page, html)
    assert got["ok"] is True, "it was read, and it was empty"
    assert got["emptyDay"] is True
    assert fdot.showed_up(got["rows"]) == []


def test_a_page_that_says_nothing_at_all_still_fails(page):
    """No banner AND no sentence = we could not tell. That must stop the week,
    not report nobody."""
    got = _read(page, "<!doctype html><html><body><div>Loading…</div></body></html>")
    assert got["ok"] is False
    assert not got.get("emptyDay")
