"""Does the field finder actually land on the right box?

`apex.find_field` locates each value by the LABEL a person reads beside it,
because nobody could reach a logged-in Apex screen while this was written. That
makes the label list the riskiest thing in the module: get a wording wrong and
the run either skips the person (loud, fine) or types into the neighbouring box
(silent, and it ends up on a payroll record).

So the ADD ROSTER EMPLOYEE screen is rebuilt here as a fixture from Megan's
screenshot of it (2026-09-03) -- the same labels in the same order, including
the two traps that screen actually contains:

  * 'First Name' / 'Middle Name' / 'Last Name' all end in 'Name', and
    'User Name' does too.
  * 'Account Email' sits beside nothing else email-shaped, but 'Email' is a
    substring of it -- so a lazy match on 'email' must not claim it for the
    person's personal address, which belongs to a different box on a later page.

WHAT THIS PROVES, AND WHAT IT DOESN'T. It proves the matcher and the label list
agree with the wordings on that screen. It does NOT prove Apex's real markup
ties its labels to its inputs the way this fixture does -- only --explore on the
live page can settle that. When it can, this fixture should be replaced with the
structure `apex_screen.json` reports.
"""
from __future__ import annotations

import pytest

from automations.apex_new_starts import apex as AX

pytest.importorskip("patchright.sync_api")

# The screen as it reads, top to bottom. Ids are invented -- if they mattered
# the test would be worthless, because the whole point is that the LABEL is what
# does the finding.
FORM = """
<!doctype html><html><body>
<h1>ADD ROSTER EMPLOYEE</h1>
<button>Save</button> <a href="/roster">Back to Roster</a>

<h2>Apex User Account</h2>
<label for="f1">First Name *</label><input id="f1" name="FirstName">
<label for="f2">Middle Name</label><input id="f2" name="MiddleName">
<label for="f3">Last Name *</label><input id="f3" name="LastName">
<label for="f4">User Name *</label><input id="f4" name="UserName">
<label for="f5">Account Email *</label><input id="f5" name="AccountEmail">
<label for="f6"><input type="checkbox" id="f6" checked>
  Send this user a password reset to their Account Email.</label>

<h2>Employment Record</h2>
<label for="f7">Hire Date *</label><input id="f7" name="HireDate" placeholder="MM/dd/yyyy">
<label for="f8">Office *</label><select id="f8" name="Office"><option>Arlington</option></select>
<label for="f9">Pay Frequency *</label>
  <select id="f9" name="PayFrequency"><option>Select</option><option>Weekly</option></select>
<label for="f10">Position *</label>
  <select id="f10" name="Position"><option>Select</option><option>Sales Rep</option></select>
<label for="f11">Rate *</label><input id="f11" name="Rate">
<label for="f12">State *</label>
  <select id="f12" name="State"><option>Select</option><option>Texas</option></select>
<label for="f13">Basis of Pay *</label>
  <select id="f13" name="BasisOfPay"><option>Select</option><option>Commissions</option></select>
</body></html>
"""

STAGE_ONE = ("first", "middle", "last", "username", "account_email",
             "hire_date", "office", "pay_frequency", "position", "rate",
             "pay_state", "pay_basis")

EXPECTED_ID = {
    "first": "f1", "middle": "f2", "last": "f3", "username": "f4",
    "account_email": "f5", "hire_date": "f7", "office": "f8",
    "pay_frequency": "f9", "position": "f10", "rate": "f11",
    "pay_state": "f12", "pay_basis": "f13",
}


@pytest.fixture(scope="module")
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        pg.set_content(FORM)
        yield pg
        browser.close()


@pytest.mark.parametrize("semantic", STAGE_ONE)
def test_every_stage_one_field_is_found_and_is_the_right_one(page, semantic):
    hit = AX.find_field(page, semantic)
    assert hit is not None, (
        f"{semantic!r} matched nothing. LABELS[{semantic!r}] = "
        f"{AX.LABELS.get(semantic)}, and the screen reads "
        f"{[k for k in EXPECTED_ID]}.")
    assert hit["id"] == EXPECTED_ID[semantic], (
        f"{semantic!r} landed on #{hit['id']} via {hit['matched_label']!r} — "
        f"expected #{EXPECTED_ID[semantic]}. A wrong box here is a wrong "
        "number on somebody's payroll record.")


def test_the_four_name_boxes_do_not_steal_each_other(page):
    """'First Name', 'Middle Name', 'Last Name' and 'User Name' all end the
    same way. Four distinct boxes or the record is scrambled."""
    ids = {s: AX.find_field(page, s)["id"]
           for s in ("first", "middle", "last", "username")}
    assert len(set(ids.values())) == 4, ids


def test_the_ssn_is_never_even_looked_for(page):
    """There is no SSN box on this screen, and there must be no attempt to find
    one anywhere. plan_fill drops it before it reaches the page."""
    matched, unmatched = AX.plan_fill(page, {"first": "Ann", "ssn": "123-45-6789"})
    assert [m[0] for m in matched] == ["first"]
    assert ("ssn", "never auto-typed — enter by hand") in unmatched


def test_the_password_reset_checkbox_is_left_alone(page):
    """It is ticked by default and mails a real new hire. Nothing in the fill
    plan may touch it -- the operator sees it and decides."""
    values = dict.fromkeys(STAGE_ONE, "x")
    matched, _ = AX.plan_fill(page, values)
    assert "f6" not in {m[2]["id"] for m in matched}
    assert page.locator("#f6").is_checked()
