"""The 'Fill Apex' button, run for real against the rebuilt Apex screens.

This is the only part of the report that will actually touch Apex, and it runs
as JavaScript inside somebody else's browser -- so it gets tested the same way
the Python does: load the screen, click the button, check the boxes hold what
they should.
"""
from __future__ import annotations

import pytest

from automations.apex_new_starts import filler

pytest.importorskip("patchright.sync_api")

from automations.apex_new_starts.test_form_match import FORM as STAGE_ONE_FORM
from automations.apex_new_starts.test_stage_two import PROFILE as PROFILE_FORM

PEOPLE = [
    {"name": "Aundre Browder",
     "fields": {"First Name": "Aundre", "Last Name": "Browder",
                "User Name": "aundre@example.com",
                "Account Email": "aundre@example.com",
                "Hire Date": "09/07/2026", "Pay Frequency": "Weekly",
                "Position": "Sales Rep", "Rate of Pay": "10.00",
                "State Working In": "Texas", "Basis of Pay": "Commissions",
                "Department": "400 Sales",
                "Date of Birth": "6/28/2004", "Gender": "Female",
                "Street Address": "622 W Page Ave", "City": "Dallas",
                "State": "Texas", "Zip Code": "75208",
                "Home Phone": "2145550123"}},
    {"name": "Second Person", "fields": {"First Name": "Second"}},
]


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


def _click_button(pg, html):
    """Load a screen, run the bookmarklet, press 'Fill this page'."""
    pg.set_content(html)
    js = filler.build_js(PEOPLE, "WE 9.13")
    assert js.startswith("javascript:")
    pg.evaluate(js[len("javascript:"):])       # the bookmarklet itself
    pg.locator("#ansfill").click()
    return pg.locator("#ansout").inner_text()


def test_it_fills_the_add_employee_screen(page):
    out = _click_button(page, STAGE_ONE_FORM)
    assert page.locator("#f1").input_value() == "Aundre"
    assert page.locator("#f3").input_value() == "Browder"
    assert page.locator("#f4").input_value() == "aundre@example.com"
    assert page.locator("#f7").input_value() == "09/07/2026"
    assert page.locator("#f9").input_value() == "Weekly"
    assert page.locator("#f10").input_value() == "Sales Rep"
    assert page.locator("#f14").input_value() == "400 Sales"
    assert page.locator("#f11").input_value() == "10.00"
    assert page.locator("#r3").is_checked(), "the Sales Rep role"
    assert "Filled:" in out


def test_the_same_button_fills_the_profile_screen(page):
    """One button, whatever page you're on. A new start spans three screens and
    three buttons would be three things to get wrong."""
    _click_button(page, PROFILE_FORM)
    assert page.locator("#p7").input_value() == "6/28/2004"      # DOB
    assert page.locator("#p8").input_value() == "Female"
    assert page.locator("#p9").input_value() == "622 W Page Ave"
    assert page.locator("#p11").input_value() == ""              # Address 2
    assert page.locator("#p10").input_value() == ""              # Apt/PO Box
    assert page.locator("#p12").input_value() == "Dallas"
    assert page.locator("#p13").input_value() == "Texas"         # not 'TX'
    assert page.locator("#p14").input_value() == "75208"
    assert page.locator("#p16").input_value() == "2145550123"


def test_it_says_what_it_could_not_find(page):
    """Half a record filled silently is how a wrong one gets saved."""
    out = _click_button(page, STAGE_ONE_FORM)
    assert "Not found here" in out            # the profile fields aren't here
    assert "Date of Birth" in out


def test_the_password_reset_checkbox_is_never_touched(page):
    """It is ticked by default and mails a real new hire."""
    _click_button(page, STAGE_ONE_FORM)
    assert page.locator("#f6").is_checked()   # left exactly as Apex had it


def test_no_social_ever_rides_in_the_button():
    """The words 'Change SSN' are in there -- they are a LABEL the button looks
    for. What must never be in there is a NUMBER.

    This matters more than the other tests: the button is a URL that gets
    saved in a bookmarks bar and could be mailed around, so a Social embedded
    in it would outlive every other precaution in this report.
    """
    import json
    import re
    from automations.apex_new_starts import filler as F

    js = F.build_js(PEOPLE, "WE 9.13")
    payload = js.split("var D=", 1)[1].rsplit(", KEY=", 1)[0]
    data = json.loads(payload)                 # the only data the button holds

    for person in data:
        for label, value in person["fields"].items():
            assert not re.fullmatch(r"\d{3}-?\d{2}-?\d{4}", str(value)), (
                f"{label} for {person['name']} looks like a Social")
            assert "social" not in label.lower()
    # and the mapping cannot introduce one later
    assert not any("ssn" == k or "social" in v.lower()
                   for k, v in F.LABEL_FOR.items())


def test_the_ssn_boxes_appear_only_on_the_tax_screen(page):
    """The panel asks for a Social where Apex asks for one, and nowhere else."""
    page.set_content(STAGE_ONE_FORM)
    page.evaluate(filler.build_js(PEOPLE, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansssn").count() == 0

    page.set_content('<label for="a">Change SSN</label><input id="a">'
                     '<label for="b">Confirm SSN</label><input id="b">')
    page.evaluate(filler.build_js(PEOPLE, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansssn").count() == 1
    page.locator("#ansssn").fill("123456789")
    page.locator("#ansfill").click()
    assert page.locator("#a").input_value() == "123456789"
    assert page.locator("#b").input_value() == "123456789"
    assert page.locator("#ansssn").input_value() == ""   # cleared after use
