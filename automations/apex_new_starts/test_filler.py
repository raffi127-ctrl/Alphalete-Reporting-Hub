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


PLAIN_UL_DROPDOWN = """
<!doctype html><html><body>
<label for="GenderID_9">Gender <span>*</span></label>
<input type="hidden" id="GenderID_9">
<span class="k-widget k-dropdown" id="gdd"><span class="k-input">Not Specified</span></span>
<div id="gpop" style="display:none">
  <ul><li>Male</li><li>Female</li></ul>
</div>
</body></html>
"""

PLAIN_UL_WIRING = """() => {
  const pop = document.getElementById('gpop');
  document.getElementById('gdd').addEventListener('mousedown', () => {
    pop.style.display = 'block';
  });
  pop.querySelectorAll('li').forEach(li => li.addEventListener('click', () => {
    document.getElementById('GenderID_9').value = li.textContent;
    document.querySelector('#gdd .k-input').textContent = li.textContent;
    pop.style.display = 'none';
  }));
}"""


def test_an_option_list_with_no_kendo_classes_still_works(page):
    """The Gender dropdown opened on the live page and then just sat there: the
    click had worked and the list was on screen, but the selector insisted on
    ul.k-list / ul.k-reset and this one wears neither."""
    page.set_content(PLAIN_UL_DROPDOWN)
    page.evaluate(PLAIN_UL_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Gender": "Male"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#GenderID_9").input_value() == "Male"
    assert page.locator("#gpop").is_hidden()


PENDING_LIST = """
<!doctype html><html><body>
<table><tbody>
<tr><td>Aundre</td><td>Browder</td><td>aundrebrowder22@gmail.com</td>
    <td><a href="/employees/2816109/edit/employment-record">Edit</a></td></tr>
<tr><td>tayshaun</td><td>funches</td><td>1835950@apex</td>
    <td><a href="/employees/2816110/edit/employment-record">Edit</a></td></tr>
</tbody></table>
</body></html>
"""


def _served(page, html, tmp_path):
    """A real origin. about:blank has no localStorage -- the button copes
    (every access is wrapped) but a test has to be able to read it back."""
    f = tmp_path / "page.html"
    f.write_text(html)
    page.goto(f.as_uri())


def test_it_learns_where_everyone_is_from_the_pending_list(page, tmp_path):
    """Finding 23 people by hand in a list, three tabs each, is the slowest
    part of the job. Every row's Edit link carries the employee's id, so one
    click on that list is enough to jump straight to people afterwards."""
    _served(page, PENDING_LIST, tmp_path)
    people = [{"name": "Aundre Browder", "find": "Browder", "fields": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])

    stored = page.evaluate(
        "() => JSON.parse(localStorage.getItem('apexNewStarts.WE 9.13.ids'))")
    assert stored["aundre browder"] == "2816109"
    assert stored["tayshaun funches"] == "2816110"
    # and the panel now offers the three tabs for this person
    assert page.locator("#ansg1").count() == 1
    assert page.locator("#ansg3").count() == 1


def test_without_that_list_it_says_how_to_teach_it(page, tmp_path):
    _served(page, "<h1>somewhere else</h1>", tmp_path)
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Nobody Known", "find": "Known", "fields": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansg1").count() == 0
    assert "Pending" in page.locator("#anspanel").inner_text()


NAV_PLUS_DROPDOWN = """
<!doctype html><html><body>
<nav><ul><li>View Profile</li><li>Account Settings</li><li>Log Off</li></ul></nav>
<ul><li>Employees</li><li>Employment Record</li><li>Tax &amp; Bank Information</li></ul>
<label for="GenderID_9">Gender <span>*</span></label>
<input type="hidden" id="GenderID_9">
<span class="k-widget k-combobox" id="gdd"><span class="k-input">Not Specified</span></span>
<div class="k-animation-container" id="gpop" style="display:none">
  <ul class="k-list"><li>Male</li><li>Female</li></ul>
</div>
</body></html>
"""

NAV_WIRING = """() => {
  const pop = document.getElementById('gpop');
  document.getElementById('gdd').addEventListener('mousedown', () => {
    pop.style.display = 'block';
  });
  pop.querySelectorAll('li').forEach(li => li.addEventListener('click', () => {
    document.getElementById('GenderID_9').value = li.textContent;
    document.querySelector('#gdd .k-input').textContent = li.textContent;
    pop.style.display = 'none';
  }));
}"""


def test_the_sites_own_menus_are_not_mistaken_for_the_dropdown(page):
    """On the live page three visible <ul>s existed before any click -- the
    nav menus -- so the search for "male" went hunting through "log off" and
    "employees" and reported that gender would not set. Only lists that appear
    BECAUSE of the click count, and a real widget popup always wins."""
    page.set_content(NAV_PLUS_DROPDOWN)
    page.evaluate(NAV_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Gender": "Male"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#GenderID_9").input_value() == "Male"


COMBOBOX = """
<!doctype html><html><body>
<label for="GenderID_9">Gender <span>*</span></label>
<input type="hidden" id="GenderID_9">
<span class="k-widget k-combobox" id="gdd">
  <span class="k-dropdown-wrap"><input type="text" class="k-input" id="gvis"></span>
</span>
</body></html>
"""

COMBOBOX_WIRING = """() => {
  /* A combobox that only ever commits on blur, and never opens a popup from a
     click on its wrapper -- which is what the live one does. */
  const vis = document.getElementById('gvis');
  vis.addEventListener('blur', () => {
    if (['Male', 'Female'].includes(vis.value)) {
      document.getElementById('GenderID_9').value = vis.value;
    } else { vis.value = ''; }
  });
}"""


def test_a_combobox_is_typed_into_not_clicked(page):
    """The live Gender control is a k-combobox and its popup never opened:
    "lists after 2500ms: 0 / after arrow click: 0". A combobox is a text box
    with a list attached -- typing is what it is for."""
    page.set_content(COMBOBOX)
    page.evaluate(COMBOBOX_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Gender": "Male"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#gvis").input_value() == "Male"
    assert page.locator("#GenderID_9").input_value() == "Male"


def test_a_value_the_combobox_rejects_is_reported(page):
    page.set_content(COMBOBOX)
    page.evaluate(COMBOBOX_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Gender": "Astronaut"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#GenderID_9").input_value() == ""
    assert "Gender" in page.locator("#ansout").inner_text()


ANGULAR_INVALID = """
<!doctype html><html><body>
<label for="a1">City <span>*</span></label><input id="a1" class="ng-valid">
<label for="a2">Mobile Phone</label><input id="a2" class="ng-invalid ng-invalid-required">
<label for="a3">Emergency Contact <span>*</span></label>
<input id="a3" class="ng-invalid ng-invalid-required">
</body></html>
"""


def test_it_names_the_fields_apex_is_objecting_to(page):
    """Apex answers a bad save with "The form is invalid" and names nothing at
    all. Angular has already stamped the offending controls ng-invalid, so the
    panel asks it and reports the captions -- which is the difference between
    a fixable message and an afternoon."""
    page.set_content(ANGULAR_INVALID)
    people = [{"name": "X", "find": "X", "fields": {"City": "Plano"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    out = page.locator("#ansout").inner_text()
    assert "still says these are invalid" in out
    assert "mobile phone" in out.lower()
    assert "emergency contact" in out.lower()
    assert "city" not in out.lower().split("invalid:")[1]   # the valid one isn't listed


COMBO_FREETEXT = """
<!doctype html><html><body>
<label for="GenderID_9">Gender <span>*</span></label>
<input type="hidden" id="GenderID_9">
<span class="k-widget k-combobox" id="gdd">
  <span class="k-dropdown-wrap"><input type="text" class="k-input" id="gvis"></span>
</span>
</body></html>
"""

FREETEXT_WIRING = """() => {
  /* A combobox that keeps whatever you type as a CUSTOM value: the screen
     reads Male, the bound field gets the word rather than an id. Angular is
     happy; the server is not. */
  const vis = document.getElementById('gvis');
  vis.addEventListener('blur', () => {
    document.getElementById('GenderID_9').value = vis.value;
  });
}"""


def test_free_text_in_a_combobox_counts_as_a_failure(page):
    """Apex answered "Saving failed: The request is invalid" while the page
    showed Male and Angular reported nothing wrong. That is what a custom
    combobox value looks like from the outside: right on screen, wrong
    underneath. Typing only counts if the bound field ends up holding
    something OTHER than the text we typed."""
    page.set_content(COMBO_FREETEXT)
    page.evaluate(FREETEXT_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"Gender": "Male"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    out = page.locator("#ansout").inner_text()
    assert "Gender" in out and "no matching option" in out


LYING_WIDGET = """
<!doctype html><html><body>
<label for="StateID">State <span>*</span></label>
<input type="hidden" id="StateID">
<span class="k-widget k-dropdown" id="sdd"><span class="k-input">Select</span></span>
<div class="k-animation-container" id="spop" style="display:none">
  <ul class="k-list"><li>Texas</li><li>Oklahoma</li></ul>
</div>
</body></html>
"""

LYING_WIRING = """() => {
  /* Updates only what you SEE and never the bound id -- exactly what happened
     with State: the box read Texas and StateProvinceID was never set. */
  const pop = document.getElementById('spop');
  document.getElementById('sdd').addEventListener('mousedown', () => {
    pop.style.display = 'block';
  });
  pop.querySelectorAll('li').forEach(li => li.addEventListener('click', () => {
    document.querySelector('#sdd .k-input').textContent = li.textContent;
    pop.style.display = 'none';                 /* bound field left empty */
  }));
}"""


def test_a_widget_that_only_updates_the_display_is_not_believed(page):
    """Apex answered request.HomeAddress.StateProvinceID: "An error has
    occurred." while the page showed Texas. The display was right and the id
    behind it was never set, and the button had reported success. A set is
    only a success if the bound field ends up holding something."""
    page.set_content(LYING_WIDGET)
    page.evaluate(LYING_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"State": "Texas"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    out = page.locator("#ansout").inner_text()
    assert "State" in out and "no matching option" in out
    assert "Filled: State" not in out


TWO_HALF_BINDING = """
<!doctype html><html><body>
<div class="form-group">
  <label for="StateProvince_445">State <span>*</span></label>
  <input type="hidden" id="StateProvinceID_445" ng-model="vm...StateProvinceID">
  <span class="k-widget k-dropdown" id="sw">
    <span class="k-dropdown-wrap"><span class="k-input">Select</span></span>
    <select id="StateProvince_445" style="display:none">
      <option value="">Select</option>
      <option value="45">Texas</option>
      <option value="36">Oklahoma</option>
    </select>
  </span>
</div>
</body></html>
"""

TWO_HALF_WIRING = """() => {
  /* Apex's shape: the <select> holds the choice, a hidden input holds the id
     the form submits, and only a BLUR copies one into the other. */
  const sel = document.getElementById('StateProvince_445');
  sel.addEventListener('blur', () => {
    document.getElementById('StateProvinceID_445').value = sel.value;
  });
  window.jQuery = el => ({data: k => (k === 'kendoDropDownList' && el === sel) ? {
    options: {dataTextField: 'text', dataValueField: 'value'},
    dataSource: {data: () => [{text: 'Texas', value: '45'},
                              {text: 'Oklahoma', value: '36'}]},
    value: v => { sel.value = v;
                  document.querySelector('#sw .k-input').textContent =
                    sel.options[sel.selectedIndex].text; },
    trigger: () => {}
  } : null});
}"""


def test_it_blurs_so_the_id_actually_gets_written(page):
    """Apex kept returning request.HomeAddress.StateProvinceID: "An error has
    occurred." while the box showed Texas. The selection was fine -- the field
    the form SUBMITS is a separate hidden input, filled by
    ng-blur="vm.onChangeStateProvince()". Nothing ever blurred the control."""
    page.set_content(TWO_HALF_BINDING)
    page.evaluate(TWO_HALF_WIRING)
    people = [{"name": "X", "find": "X", "fields": {"State": "Texas"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)

    assert page.locator("#StateProvince_445").input_value() == "45"
    assert page.locator("#StateProvinceID_445").input_value() == "45", \
        "the id the form submits"
    assert "Filled: State" in page.locator("#ansout").inner_text()


SELECT_INSIDE_WIDGET = """
<!doctype html><html><body>
<div class="form-group">
  <label for="MaritalStatus_1">Marital Status <span>*</span></label>
  <span class="k-widget k-dropdown" id="mw">
    <span class="k-dropdown-wrap"><span class="k-input">Select</span></span>
    <select id="MaritalStatus_1" style="display:none">
      <option value="">Select</option>
      <option value="1">Single or Married filing separately</option>
      <option value="2">Married filing jointly</option>
    </select>
  </span>
  <input type="hidden" id="MaritalStatusID" ng-model="vm.maritalStatusId">
</div>
<div class="k-animation-container" id="mpop" style="display:none">
  <ul class="k-list"><li>Select</li>
    <li>Single or Married filing separately</li><li>Married filing jointly</li></ul>
</div>
</body></html>
"""

SELECT_INSIDE_WIRING = """() => {
  const pop = document.getElementById('mpop');
  document.getElementById('mw').addEventListener('mousedown', () => {
    pop.style.display = 'block';
  });
  pop.querySelectorAll('li').forEach(li => li.addEventListener('click', () => {
    const sel = document.getElementById('MaritalStatus_1');
    for (const o of sel.options) if (o.text === li.textContent) sel.value = o.value;
    document.querySelector('#mw .k-input').textContent = li.textContent;
    pop.style.display = 'none';
    document.getElementById('MaritalStatusID').value = sel.value;
  }));
}"""


def test_a_select_inside_the_widget_is_still_reachable(page):
    """On the tax page the <select> the label points at lives INSIDE the
    k-widget span, so looking for a widget BESIDE it found nothing -- the list
    opened and was never clicked. Both shapes have to work."""
    page.set_content(SELECT_INSIDE_WIDGET)
    page.evaluate(SELECT_INSIDE_WIRING)
    people = [{"name": "X", "find": "X",
               "fields": {"Marital Status": "Single or Married filing separately"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#MaritalStatus_1").input_value() == "1"
    assert page.locator("#MaritalStatusID").input_value() == "1"
    assert page.locator("#mpop").is_hidden(), "the list closes again"


NEIGHBOUR_TRAP = """
<!doctype html><html><body>
<div class="form-group">
  <label for="TaxState_1">State to be taxed in <span>*</span></label>
  <span class="k-widget k-dropdown" id="tsw">
    <span class="k-dropdown-wrap"><span class="k-input">Select</span></span>
    <select id="TaxState_1" style="display:none">
      <option value="">Select</option><option value="45">Texas</option>
    </select>
  </span>
</div>
<div class="form-group">
  <label for="FedAmt">Federal</label>
  <input type="text" id="FedAmt" placeholder="Amount ($0.00)">
</div>
</body></html>
"""


def test_it_never_writes_into_a_neighbouring_field(page):
    """This is the one that matters most. A widget span resolved one level too
    high reached into the NEXT field and typed "Texas" into "Additional Tax
    Amount Withheld -> Federal" -- a money box, on a tax record. Whatever else
    happens, a value must never land outside the field it was meant for."""
    page.set_content(NEIGHBOUR_TRAP)
    people = [{"name": "X", "find": "X",
               "fields": {"State to be taxed in": "Texas"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#FedAmt").input_value() == "", \
        "the neighbouring money box must be untouched"


NO_LABEL_AT_ALL = """
<!doctype html><html><body>
<div class="row"><div class="col-md-4"><div class="form-group">
  Claim Dependants <span class="fas fa-question-circle"></span>
  <span class="k-widget k-numerictextbox">
    <span class="k-numeric-wrap">
      <input type="text" class="k-formatted-value" aria-hidden="true" id="pretty">
      <input type="text" id="ClaimDependants" ng-model="vm.claim">
    </span>
  </span>
</div></div></div>
<div class="row form-group"><div class="col-md-3"><div>
  State to be taxed in <div class="RequiredText">*</div>
  <span class="k-widget k-combobox">
    <span class="k-dropdown-wrap">
      <input name="StateToBeTaxedIn_input" class="k-input" type="text" id="taxstate">
    </span>
  </span>
</div></div></div>
</body></html>
"""


def test_fields_with_no_label_element_are_still_found(page):
    """Claim Dependants and State to be taxed in have no <label> anywhere --
    the caption is a bare text node in the form-group. Every lookup started
    from a <label>, so neither field was findable by any route, and both sat
    empty through several rounds of me blaming the widgets."""
    page.set_content(NO_LABEL_AT_ALL)
    people = [{"name": "X", "find": "X",
               "fields": {"Claim Dependants": "0.00",
                          "State to be taxed in": "Texas"}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#ClaimDependants").input_value() == "0.00"
    assert page.locator("#taxstate").input_value() == "Texas"
    assert page.locator("#pretty").input_value() == "", \
        "the aria-hidden display input is not the one to write to"
