"""The employee's own record -- 'User Profile & Account'.

Rebuilt from a real saved employee (Andrea Herrera, 2026-09-03). This page is
where the address and date of birth go, and it carries the nastiest label
collision in the whole report:

    Street Address        the one we fill
    Street Address 2      empty, and a substring match hits it too
    Apt/PO Box            a THIRD address box, for the I-9's apartment field

Plus two conversions the I-9 forces, because it does not speak Apex:

    state   the I-9 writes 'TX'; this dropdown holds 'Texas'. Selecting 'TX'
            selects NOTHING -- silently, with no error.
    phone   the I-9 holds ten digits; the record has separate Home and Mobile
            boxes, and the existing rows carry an 11-digit form.
"""
from __future__ import annotations

import pytest

from automations.apex_new_starts import apex as AX

pytest.importorskip("patchright.sync_api")

PROFILE = """
<!doctype html><html><body>
<button>Save</button>
<h2>Apex User Account for Andrea Herrera</h2>
<label for="p1">First Name *</label><input id="p1" value="Andrea">
<label for="p2">Middle Name</label><input id="p2">
<label for="p3">Last Name *</label><input id="p3" value="Herrera">
<span>User Name</span><div>dtxandri@gmail.com</div>
<label for="p5">Account Email *</label><input id="p5" value="dtxandri@gmail.com">
<button id="sendreset">Send Password Reset</button>
<label for="p6"><input type="checkbox" id="p6">
  Override the user's password with a temporary password.</label>

<h2>Employee Profile for Andrea Herrera</h2>
<label for="p7">Date of Birth *</label><input id="p7" value="6/28/2004">
<label for="p8">Gender *</label>
  <select id="p8"><option>Select</option><option>Female</option>
  <option>Male</option></select>

<h3>Address</h3>
<label for="p9">Street Address *</label><input id="p9">
<label for="p10">Apt/PO Box</label><input id="p10">
<label for="p11">Street Address 2</label><input id="p11">
<label for="p12">City *</label><input id="p12">
<label for="p13">State *</label>
  <select id="p13"><option>Select</option><option>Texas</option>
  <option>Oklahoma</option></select>
<label for="p14">Zip Code *</label><input id="p14">
<label for="p15">Country *</label>
  <select id="p15"><option>United States</option></select>

<h3>Home Phone</h3><label for="p16">Home Phone</label><input id="p16">
<label for="p17">Ext</label><input id="p17" placeholder="Ext">
<h3>Mobile Phone</h3><label for="p18">Mobile Phone</label>
  <input id="p18" placeholder="Phone #">
</body></html>
"""

EXPECTED_ID = {
    "dob": "p7", "gender": "p8", "address1": "p9", "apt": "p10",
    "address2": "p11", "city": "p12", "state": "p13", "zip": "p14",
    "country": "p15", "home_phone": "p16", "mobile_phone": "p18",
}


@pytest.fixture(scope="module")
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        pg.set_content(PROFILE)
        yield pg
        browser.close()


@pytest.mark.parametrize("semantic", sorted(EXPECTED_ID))
def test_every_stage_two_field_is_found_and_is_the_right_one(page, semantic):
    hit = AX.find_field(page, semantic)
    assert hit is not None, (
        f"{semantic!r} matched nothing; LABELS = {AX.LABELS.get(semantic)}")
    assert hit["id"] == EXPECTED_ID[semantic], (
        f"{semantic!r} landed on #{hit['id']} via {hit['matched_label']!r}")


def test_the_three_address_boxes_stay_apart(page):
    """'Street Address', 'Street Address 2' and 'Apt/PO Box'. A substring match
    on 'street address' hits two of them and fills neither; a home address in
    the Apt box is a wrong address on a payroll record."""
    ids = {s: AX.find_field(page, s)["id"]
           for s in ("address1", "address2", "apt")}
    assert ids == {"address1": "p9", "address2": "p11", "apt": "p10"}


def test_the_state_dropdown_needs_the_full_name(page):
    """The I-9 says 'TX'. Selecting 'TX' here selects nothing, silently."""
    assert AX.STATE_NAMES["TX"] == "Texas"
    hit = AX.find_field(page, "state")
    AX.apply_fill(page, [("state", AX.STATE_NAMES["TX"], hit)],
                  log=lambda *_: None)
    assert page.locator("#p13").input_value() == "Texas"


def test_the_password_controls_are_untouchable(page):
    """'Send Password Reset' MAILS somebody and the override checkbox sets a
    password. Neither may ever be in a fill plan."""
    matched, _ = AX.plan_fill(page, dict.fromkeys(EXPECTED_ID, "x"))
    assert {"sendreset", "p6"}.isdisjoint({m[2]["id"] for m in matched})


def test_gender_is_found_and_now_comes_from_the_board(page):
    """Apex requires it and no form asks for it, so Megan added a Gender column
    to the sales board's New Starts box (2026-09-03). The run reads that cell;
    it never infers a gender from somebody's name."""
    assert AX.find_field(page, "gender")["id"] == "p8"
    assert AX.UNANSWERED == ()


SSN_FORM = """
<!doctype html><html><body>
<label for="s1">Social Security Number *</label><input id="s1">
<label for="s2">City</label><input id="s2">
</body></html>
"""


def test_the_social_goes_in_only_through_its_own_door(page):
    """The Social is looked up outside LABELS, so plan_fill -- the path every
    ordinary value travels -- cannot reach that box even by accident. Only
    fill_ssn can, and only with a Secret a person typed."""
    from automations.apex_new_starts.ssn_prompt import Secret
    page.set_content(SSN_FORM)
    matched, unmatched = AX.plan_fill(page, {"ssn": "123456789",
                                             "city": "Irving"})
    assert [m[0] for m in matched] == ["city"]
    assert ("ssn", "never auto-typed — enter by hand") in unmatched
    assert page.locator("#s1").input_value() == ""

    assert AX.fill_ssn(page, Secret("123456789")) is True
    assert page.locator("#s1").input_value() == "123456789"


def test_fill_ssn_types_nothing_when_it_cant_find_the_box(page):
    """The Tax & Bank tab has never been seen, so the label wordings are a
    guess. A guess that lands on the wrong box would put a Social somewhere it
    doesn't belong -- so a miss types nothing at all."""
    from automations.apex_new_starts.ssn_prompt import Secret
    page.set_content('<label for="x">City</label><input id="x">')
    assert AX.fill_ssn(page, Secret("123456789")) is False
    assert page.locator("#x").input_value() == ""
