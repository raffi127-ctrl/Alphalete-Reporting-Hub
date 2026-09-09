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
    _settled(pg)
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
    _settled(page)
    assert page.locator("#a").input_value() == "123456789"
    assert page.locator("#b").input_value() == "123456789"
    assert page.locator("#ansssn").input_value() == ""   # cleared after use


def test_the_tax_screen_offers_their_blue_ink_packet(page):
    """Read the Social off their own signed I-9, beside the box it goes in."""
    page.set_content('<label for="a">Change SSN</label><input id="a">'
                     '<label for="b">Confirm SSN</label><input id="b">')
    people = [dict(PEOPLE[0], find="Browder")]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    href = page.locator("#ansbi").get_attribute("href")
    assert href == ("https://secure.blueink.com/dashboard/wall?search=Browder")
    assert page.locator("#ansbi").get_attribute("target") == "_blank"


def test_that_link_is_a_search_never_a_document():
    """A signed document URL embedded here would be a link to somebody's SSN
    sitting in a bookmarks bar -- which would undo the reason the number itself
    is kept out."""
    js = filler.build_js([dict(PEOPLE[0], find="Browder")], "WE 9.13")
    assert "blueinkprod.s3" not in js and "signed.pdf" not in js
    assert "AWSAccessKeyId" not in js and "Signature=" not in js


def test_no_blue_ink_link_on_the_other_screens(page):
    """It appears where the Social is asked for, and nowhere else."""
    page.set_content(STAGE_ONE_FORM)
    page.evaluate(filler.build_js(PEOPLE, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansbi").count() == 0


def test_clicking_it_on_the_wrong_page_says_so_plainly(page):
    """The first click anyone makes is on the instructions page. It used to
    answer with a wall of red listing every field that page was never going to
    have, which reads like a broken tool rather than a wrong tab."""
    page.set_content("<h1>Not Apex</h1><p>nothing here</p>")
    page.evaluate(filler.build_js(PEOPLE, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    out = page.locator("#ansout").inner_text()
    assert "isn't an Apex form" in out
    assert "Pending" in out and "Edit" in out
    assert "Not found here" not in out


def test_the_button_never_contains_a_line_comment():
    """build_js collapses the script to ONE line, so a single `//` comment
    silently swallows everything after it -- the button still saves, still
    clicks, and does nothing. Cost an afternoon once; only /* */ from here."""
    js = filler.build_js(PEOPLE, "WE 9.13")
    body = js[len("javascript:"):]
    for marker in ("http://", "https://"):
        body = body.replace(marker, "")
    body = body.replace("&&", "")          # not a comment
    assert "//" not in body, "a // comment would kill everything after it"


CAPTIONS_NOT_LABELS = """
<!doctype html><html><body>
<div><div>Position *</div>
  <select id="c1"><option>Select</option><option>Sales Rep</option></select>
  <div>Position is required.</div></div>
<div><span>Rate of Pay *</span><input id="c2"></div>
<div><p>Department *</p>
  <select id="c3"><option>Select</option><option>400 Sales</option></select></div>
</body></html>
"""


def test_it_finds_boxes_whose_caption_is_not_a_label_tag(page):
    """Apex's Employment Record writes 'Position *' as plain text beside the
    <select>, not as a <label>. The button filled the top of the form on the
    live page and silently missed all six of these."""
    page.set_content(CAPTIONS_NOT_LABELS)
    people = [{"name": "Aundre Browder", "find": "Browder",
               "fields": {"Position": "Sales Rep", "Rate of Pay": "10.00",
                          "Department": "400 Sales"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#c1").input_value() == "Sales Rep"
    assert page.locator("#c2").input_value() == "10.00"
    assert page.locator("#c3").input_value() == "400 Sales"


KENDO_FORM = """
<!doctype html><html><body>
<div class="form-group">
  <label for="JobTitleID_943">Position <span>*</span></label>
  <input type="hidden" id="JobTitleID_943" name="JobTitleID_943">
  <span class="k-widget k-dropdown" role="listbox">Select</span>
</div>
<div class="form-group">
  <label for="PlainCity">City <span>*</span></label>
  <input type="text" id="PlainCity">
</div>
</body></html>
"""

# The smallest thing that behaves like jQuery + Kendo: a widget bound to the
# hidden input whose value only changes through its own API. Installed by
# evaluate() rather than an inline <script>, which set_content does not run.
KENDO_STUB = """() => {
  window.__set = [];
  const W = {
    options: {dataTextField: 'Text', dataValueField: 'Value'},
    dataSource: {data: () => ([
        {Text: 'Select', Value: ''},
        {Text: 'Sales Rep', Value: '17'},
        {Text: 'Office Admin', Value: '4'}])},
    value: v => { document.getElementById('JobTitleID_943').value = v;
                  window.__set.push(v); },
    trigger: () => {}
  };
  window.jQuery = el => ({
    data: k => (k === 'kendoDropDownList' && el && el.id === 'JobTitleID_943')
               ? W : null
  });
}"""


def _settled(page):
    """Filling is async now -- a Kendo dropdown is opened, waited for, clicked.
    The click returns long before that finishes."""
    page.wait_for_function(
        "() => { const o = document.getElementById('ansout');"
        "        return o && o.innerHTML && o.innerHTML !== 'filling...'; }",
        timeout=15000)


def _kendo_page(page, fields):
    page.set_content(KENDO_FORM)
    page.evaluate(KENDO_STUB)
    people = [{"name": "Aundre Browder", "find": "Browder", "fields": fields}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)


def test_it_drives_kendo_dropdowns_through_their_own_api(page):
    """Apex's dropdowns are Kendo widgets on AngularJS: the <label for> points
    at a HIDDEN input and the visible control is a span. Setting .value on the
    input does nothing at all -- which is why six fields silently stayed on
    'Select' through three rounds of guessing."""
    _kendo_page(page, {"Position": "Sales Rep", "City": "Dallas"})
    assert page.evaluate("window.__set") == ["17"], "set by VALUE, matched on text"
    assert page.locator("#PlainCity").input_value() == "Dallas", "plain inputs still work"
    assert "Position" in page.locator("#ansout").inner_text()


def test_a_hidden_kendo_input_is_not_skipped_as_invisible(page):
    """The rule everywhere else is 'never type into something hidden'. A
    Kendo-backed input is the one exception: it is SUPPOSED to be hidden, and
    refusing it is what made these fields unreachable."""
    _kendo_page(page, {"Position": "Office Admin"})
    assert page.evaluate("window.__set") == ["4"]


# A dropdown that behaves like Apex's: the <label> points at a HIDDEN input,
# the visible control is a k-dropdown span, and NOTHING answers to .data() or
# kendo.widgetInstance. The only way in is the way a person goes -- click the
# span, click the option.
CLICKY_KENDO = """
<!doctype html><html><body>
<div class="form-group">
  <label for="JobTitleID_943">Position <span>*</span></label>
  <input type="hidden" id="JobTitleID_943">
  <span class="k-widget k-dropdown" id="ddl"><span class="k-input">Select</span></span>
  <div class="k-animation-container" id="pop" style="display:none">
    <ul class="k-list">
      <li>Select</li><li>Office Admin</li><li>Sales Rep</li>
    </ul>
  </div>
</div>
</body></html>
"""

CLICKY_WIRING = """() => {
  const pop = document.getElementById('pop');
  document.getElementById('ddl').addEventListener('mousedown', () => {
    pop.style.display = 'block';                 /* opens on mousedown, as Kendo does */
  });
  pop.querySelectorAll('li').forEach(li => {
    li.addEventListener('click', () => {
      document.getElementById('JobTitleID_943').value = li.textContent;
      document.querySelector('#ddl .k-input').textContent = li.textContent;
      pop.style.display = 'none';
    });
  });
}"""


def test_a_dropdown_with_no_api_is_still_filled_by_clicking(page):
    """On the live page .data() and kendo.widgetInstance both came back empty
    for the dropdowns, while the NumericTextBox answered fine. A real click
    cannot be wrong about which control it is talking to."""
    page.set_content(CLICKY_KENDO)
    page.evaluate(CLICKY_WIRING)
    people = [{"name": "Aundre Browder", "find": "Browder",
               "fields": {"Position": "Sales Rep"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)

    assert page.locator("#JobTitleID_943").input_value() == "Sales Rep"
    assert page.locator("#ddl .k-input").inner_text() == "Sales Rep"
    assert "Position" in page.locator("#ansout").inner_text()
    assert page.locator("#pop").is_hidden(), "the list closes again"


def test_an_option_that_isnt_in_the_list_leaves_it_alone(page):
    """Better an honest miss than the wrong option on a payroll record."""
    page.set_content(CLICKY_KENDO)
    page.evaluate(CLICKY_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Position": "Astronaut"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#JobTitleID_943").input_value() == ""
    assert "Position" in page.locator("#ansout").inner_text()


PROFILE_WITH_GENDER = """
<!doctype html><html><body>
<label for="g1">Gender <span>*</span></label>
<select id="g1"><option>Not Specified</option><option>Female</option>
  <option>Male</option></select>
<label for="c1">City <span>*</span></label><input id="c1">
</body></html>
"""


def test_it_asks_for_gender_when_the_board_has_none(page):
    """Gender is required on the profile page and the board's column is usually
    still empty when this runs. Without it Apex refuses the WHOLE page with
    "The request is invalid" and names no field, which is impossible to debug
    from the outside."""
    page.set_content(PROFILE_WITH_GENDER)
    people = [{"name": "Aundre Browder", "find": "Browder",
               "fields": {"City": "Dallas"}}]          # no Gender
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansgender").count() == 1

    page.select_option("#ansgender", "Female")
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#g1").input_value() == "Female"
    assert "gender Female" in page.locator("#ansout").inner_text()


def test_it_warns_rather_than_saving_a_page_apex_will_reject(page):
    """Filling without picking one leaves a required field empty. Say so, in
    the panel, instead of letting Save fail with a message that names nothing."""
    page.set_content(PROFILE_WITH_GENDER)
    people = [{"name": "X", "find": "X", "fields": {"City": "Dallas"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    out = page.locator("#ansout").inner_text()
    assert "Gender is required" in out


def test_no_gender_prompt_when_the_board_supplied_one(page):
    page.set_content(PROFILE_WITH_GENDER)
    people = [{"name": "X", "find": "X",
               "fields": {"City": "Dallas", "Gender": "Male"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansgender").count() == 0
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#g1").input_value() == "Male"
