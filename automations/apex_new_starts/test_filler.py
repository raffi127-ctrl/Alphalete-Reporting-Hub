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
    # the payload now sits on its own after `var D=` and ends at the semicolon
    payload = js.split("var D=", 1)[1].split("; if(!D)", 1)[0]
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


def test_it_asks_for_gender_when_the_board_has_none(page, tmp_path):
    """Gender is required on the profile page and the board's column is usually
    still empty when this runs. Without it Apex refuses the WHOLE page with
    "The request is invalid" and names no field, which is impossible to debug
    from the outside."""
    # served from a user-profile url: the prompt is decided by which PAGE you
    # are on, not by whether the control can be found
    f = tmp_path / "user-profile.html"
    f.write_text(PROFILE_WITH_GENDER)
    page.goto(f.as_uri())
    people = [{"name": "Aundre Browder", "find": "Browder",
               "pages": {"profile": {"City": "Dallas"}}}]      # no Gender
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansgender").count() == 1

    page.select_option("#ansgender", "Female")
    page.locator("#ansfill").click()
    _settled(page)
    assert page.locator("#g1").input_value() == "Female"
    assert "gender Female" in page.locator("#ansout").inner_text()


def test_it_warns_rather_than_saving_a_page_apex_will_reject(page, tmp_path):
    """Filling without picking one leaves a required field empty. Say so, in
    the panel, instead of letting Save fail with a message that names nothing."""
    f = tmp_path / "user-profile.html"
    f.write_text(PROFILE_WITH_GENDER)
    page.goto(f.as_uri())
    people = [{"name": "X", "find": "X",
               "pages": {"profile": {"City": "Dallas"}}}]
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
    # that hint only shows on a person's record now -- on the roster the panel
    # is about the week, not about one person
    f2 = tmp_path / "user-profile.html"
    f2.write_text("<h1>profile</h1>")
    page.goto(f2.as_uri())
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
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


TAX_PAGE_WITH_STATE_CAPTION = """
<!doctype html><html><body>
<div class="row form-group"><div class="col-md-3"><div>
  State to be taxed in <div class="RequiredText">*</div>
  <span class="k-widget k-combobox"><span class="k-dropdown-wrap">
    <input name="StateToBeTaxedIn_input" class="k-input" type="text" id="taxstate">
  </span></span>
</div></div></div>
<div class="form-group">
  Additional Tax Amount Withheld for Each Pay Statement
  <div>Federal<input type="text" id="fed" placeholder="Amount ($0.00)"></div>
  <div>State<input type="text" id="stateamt" placeholder="Amount ($0.00)"></div>
</div>
</body></html>
"""


def test_a_home_address_field_never_reaches_the_tax_page(page, tmp_path):
    """"State" is the home address on the PROFILE page. On the TAX page the
    only thing called State is the second money box under Additional Tax
    Amount Withheld -- and "Texas" landed in the one beside it. Fields are
    offered only to the page they belong to."""
    f = tmp_path / "bank-info.html"          # the url is what identifies a page
    f.write_text(TAX_PAGE_WITH_STATE_CAPTION)
    page.goto(f.as_uri())
    people = [{"name": "X", "find": "X", "pages": {
        "profile": {"State": "Texas", "City": "Plano"},
        "tax": {"State to be taxed in": "Texas"}}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    _settled(page)

    assert page.locator("#taxstate").input_value() == "Texas"
    assert page.locator("#fed").input_value() == "", "the money box stays empty"
    assert page.locator("#stateamt").input_value() == ""


def test_the_button_is_handed_pages_not_a_flat_field_list():
    """rows_for() returns {page: {label: value}}. run.py went on assigning it
    to "fields", so the button iterated the PAGE NAMES as if they were fields
    and wrote "[object Object]" into a money box on the tax page. The shape the
    generator emits and the shape the button expects have to match."""
    import datetime as dt
    from automations.apex_new_starts import board as BRD
    from automations.apex_new_starts import blueink_data as BID
    from automations.apex_new_starts import run as RUN

    c = BRD.Candidate(name="Ann Lee", trainer="", email="", location="",
                      team="", reason_lost="", roll={0: "CR"}, tab="t", row=1,
                      week_start=dt.date(2026, 9, 7), gender="Female")
    hire = BID.NewHire(name="Ann Lee",
                       values={"first": "Ann", "last": "Lee", "state": "TX",
                               "city": "Plano"})
    pages = filler.rows_for(RUN.apex_values(c, hire))

    assert set(pages) <= {"employment", "profile", "tax"}
    for page, fields in pages.items():
        for label, value in fields.items():
            assert isinstance(value, str), f"{page}/{label} is not a string"
    assert pages["profile"]["State"] == "Texas"
    assert "State" not in pages.get("tax", {})


def test_the_gender_prompt_does_not_depend_on_finding_the_box(page, tmp_path):
    """It used to only appear if fieldFor('Gender') succeeded, so a lookup miss
    silently removed the prompt -- and the operator found out the required
    field was empty when Apex refused the save. The question is whether the
    PAGE wants a gender, not whether the box can be located."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>profile with no gender control at all</h1>")
    page.goto(f.as_uri())
    people = [{"name": "Cristian Amaya Vega", "find": "Vega",
               "pages": {"profile": {"City": "Seagoville"}}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansgender").count() == 1


def test_no_gender_prompt_on_the_tax_page(page, tmp_path):
    """It appeared on the tax page too, which has no Gender field, and then
    reported that it could not set it."""
    f = tmp_path / "bank-info.html"
    f.write_text("<h1>tax page</h1>")
    page.goto(f.as_uri())
    people = [{"name": "X", "find": "X", "pages": {"tax": {}}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert page.locator("#ansgender").count() == 0


def test_the_run_engine_and_setup_form_are_in_the_button():
    """One form for the week, then one pass over everybody. Filling every field
    and leaving 69 Saves to a person was not saving meaningful time."""
    js = filler.build_js([{"name": "A", "find": "A", "pages": {"tax": {}}}],
                         "WE 9.13")
    for piece in ("runPerson", "goSpa", "saveHere", "ansrun", "ansgo",
                  "Run the whole week"):
        assert piece in js, piece
    # it must never reload: a reload kills the script mid-run
    assert "location.href=path" not in js


def test_socials_are_never_persisted_by_the_run():
    """They are typed into the setup form, held in the page for the run, and
    that is all. Nothing about them may reach localStorage."""
    js = filler.build_js([{"name": "A", "find": "A", "pages": {}}], "WE 9.13")
    body = js[len("javascript:"):]
    for chunk in body.split("localStorage.setItem")[1:]:
        head = chunk[:80].lower()
        assert "ssn" not in head and "__anssn" not in head


def test_each_row_opens_that_persons_document_in_the_pane(page, tmp_path):
    """A deliberate reversal, and it should be visible here.

    The rule used to be that a signed-document URL must never appear in this
    list, because it is a link to somebody's SSN inside a file that can be
    copied between machines. The search link honoured that -- and it meant
    searching Blue Ink, opening the envelope and hunting for Quick View for
    each of 23 people, which Megan judged too slow to use (2026-09-10).

    So the list now carries Blue Ink's own expiring link to each signed W-4,
    and it opens beside the box. What that costs: those links are live for a
    few hours, and they travel in the pasted list. What it must never become
    is us reading the number ITSELF -- the operator still types it.
    """
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {},
               "doc": "https://blueinkprod.s3.amazonaws.com/a.pdf?Signature=x"},
              {"name": "Cristian Amaya Vega", "find": "Vega", "pages": {},
               "doc": "https://blueinkprod.s3.amazonaws.com/c.pdf?Signature=y"}]
    js = filler.build_js(people, "WE 9.13")
    page.evaluate(js[len("javascript:"):])
    page.locator("#ansrun").click()

    rows = page.locator("#anssetup [data-doc]")
    assert rows.count() == 2
    rows.nth(1).click()
    assert page.locator("#ansdoc").get_attribute("src").endswith("Signature=y")

    # the line that must hold whatever else changes
    import json
    payload = json.loads(js.split("var D=", 1)[1].split("; if(!D)", 1)[0])
    for person in payload:
        for value in person.get("pages", {}).values():
            for v in value.values():
                assert not __import__("re").fullmatch(r"\d{3}-?\d{2}-?\d{4}",
                                                     str(v))


def test_the_code_only_button_asks_for_the_list(page, tmp_path):
    """This is the exact thing the page ships, and it was completely broken:
    the paste-panel code silently failed to apply, so the button was emitted
    with `var D=null` and died on the next line reading D.length. Nothing
    appeared at all when clicked. Every test until now passed the people IN,
    so none of them exercised what the page actually hands out."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>apex</h1>")
    page.goto(f.as_uri())

    shipped = filler.build_js(None, "WE 9.13")      # code only, as shipped
    page.evaluate(shipped[len("javascript:"):])
    assert page.locator("#anspaste").count() == 1, "the paste box must appear"

    page.locator("#anspaste").fill(filler.data_json(
        [{"name": "A Person", "find": "Person",
          "pages": {"profile": {"City": "Plano"}}}]))
    page.locator("#anssave").click()
    assert page.evaluate(
        "() => !!localStorage.getItem('apexNewStarts.WE 9.13.data')")

    page.evaluate(shipped[len("javascript:"):])
    assert page.locator("#ansrun").count() == 1, "then the real panel"
    assert "A Person" in page.locator("#anspanel").inner_text()


def test_rubbish_pasted_in_is_refused(page, tmp_path):
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>apex</h1>")
    page.goto(f.as_uri())
    page.evaluate(filler.build_js(None, "WE 9.13")[len("javascript:"):])
    page.locator("#anspaste").fill("not json at all")
    page.locator("#anssave").click()
    assert "not the list" in page.locator("#anspmsg").inner_text()
    assert page.evaluate(
        "() => localStorage.getItem('apexNewStarts.WE 9.13.data')") is None


PENDING_PAGE_1 = """
<!doctype html><html><body><table><tbody>
<tr><td>Aundre</td><td>Browder</td><td>a@b.com</td>
    <td><a href="/employees/2816109/edit/employment-record">Edit</a></td></tr>
</tbody></table></body></html>
"""

PENDING_PAGE_2 = """
<!doctype html><html><body><table><tbody>
<tr><td>Cristian</td><td>Amaya Vega</td><td>c@d.com</td>
    <td><a href="/employees/2816105/edit/employment-record">Edit</a></td></tr>
</tbody></table></body></html>
"""


def test_it_says_how_many_people_it_still_cannot_find(page, tmp_path):
    """The Pending list is paginated. One click only sees the rows on screen,
    so with a week spread over five pages the run would stop dead at the first
    person it has no id for -- with nothing having warned anybody."""
    p1 = tmp_path / "roster1.html"; p1.write_text(PENDING_PAGE_1)
    p2 = tmp_path / "roster2.html"; p2.write_text(PENDING_PAGE_2)
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Cristian Amaya Vega", "find": "Vega", "pages": {}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]

    page.goto(p1.as_uri())
    page.evaluate(js)
    out = page.locator("#ansout").inner_text()
    assert "1 of 2 still not found" in out
    assert "each one" in out                      # tells you to keep clicking

    page.goto(p2.as_uri())                        # same origin: ids accumulate
    page.evaluate(js)
    assert "All 2 found" in page.locator("#ansout").inner_text()


def test_the_button_survives_being_read_out_of_an_href(page, tmp_path):
    """THE bug that made it do nothing at all. The button ships inside an
    href, and a browser DECODES HTML entities when it reads one. A "&#39;" I
    had written became a real apostrophe inside a single-quoted string --
    a syntax error, so the whole script died silently on click.

    So the test does what the browser does: put the button in a real href,
    read it back through the DOM, and run THAT."""
    page_html = (tmp_path / "page.html")
    js = filler.build_js(None, "WE 9.13")
    page_html.write_text(
        '<a id="bm" href="' + js.replace('"', "&quot;") + '">Fill Apex</a>')
    page.goto(page_html.as_uri())

    from_href = page.locator("#bm").get_attribute("href")
    assert from_href.startswith("javascript:")
    page.evaluate(from_href[len("javascript:"):])       # exactly what a click runs
    assert page.locator("#anspaste").count() == 1, \
        "it must still parse and show the paste box"


def test_no_html_entity_can_ever_ship_in_the_button():
    """A guard on the whole class, not just the one apostrophe."""
    import pytest as _pytest
    from automations.apex_new_starts import filler as F
    good = F.build_js(None, "WE 9.13")
    assert "&#39;" not in good and "&amp;" not in good

    original = F._JS
    F._JS = original.replace("No list loaded", "No list &#39;loaded")
    try:
        with _pytest.raises(RuntimeError, match="HTML entities"):
            F.build_js(None, "WE 9.13")
    finally:
        F._JS = original


ROSTER_WITH_FILTER = """
<!doctype html><html><body>
<table>
<thead><tr><th>First Name</th><th>Last Name</th><th>User Name</th><th></th></tr>
<tr><td><input placeholder="Filter" id="ff"></td>
    <td><input placeholder="Filter" id="lf"></td>
    <td><input placeholder="Filter"></td>
    <td><button id="apply">Apply Filters</button></td></tr></thead>
<tbody id="rows"></tbody>
</table>
</body></html>
"""

ROSTER_WIRING = """() => {
  /* A roster that filters in-page by surname, like Apex's does. */
  const all = [
    ['Aundre', 'Browder', '2816109'],
    ['Cristian', 'Amaya Vega', '2816105'],
    ['Kalynn', 'Nugent', '9999999']];
  window.__render = () => {
    const want = document.getElementById('lf').value.toLowerCase();
    document.getElementById('rows').innerHTML = all
      .filter(r => !want || r[1].toLowerCase().includes(want))
      .map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>x</td>
        <td><a href="/employees/${r[2]}/edit/employment-record">Edit</a></td></tr>`)
      .join('');
  };
  document.getElementById('apply').addEventListener('click', window.__render);
  /* start on a page that shows NEITHER of our people, the way page 5 of a
     five-page roster does */
  document.getElementById('lf').value = 'nugent';
  window.__render();
}"""


def test_it_looks_everyone_up_itself(page, tmp_path):
    """Clicking the button on each page of a five-page list to teach it where
    people are is exactly the chore this is meant to remove. The roster filters
    in-page, so it can find each person by surname on its own."""
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_WITH_FILTER)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_WIRING)
    page.evaluate("() => localStorage.clear()")

    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Cristian Amaya Vega", "find": "Amaya Vega", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfind").click()          # the run does this itself
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.includes('found')"
        " && !document.getElementById('ansout').innerText.includes('not found')",
        timeout=20000)

    stored = page.evaluate(
        "() => JSON.parse(localStorage.getItem('apexNewStarts.WE 9.13.ids'))")
    assert stored["aundre browder"] == "2816109"
    assert stored["cristian amaya vega"] == "2816105"
    assert page.locator("#lf").input_value() == "", "the filter is put back"


def test_the_lookup_waits_until_the_run_starts(page, tmp_path):
    """It used to start the moment the panel opened, which meant watching it
    grind through 23 surnames before you could do anything. The form comes
    first; finding people is the first step of the RUN (Megan, 2026-09-10)."""
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_WITH_FILTER)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_WIRING)
    page.evaluate("() => localStorage.clear()")

    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Cristian Amaya Vega", "find": "Amaya Vega", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])

    page.wait_for_timeout(1500)
    assert "still not found" in page.locator("#ansout").inner_text()
    # reading rows already on screen is instant and still happens; what must
    # NOT have happened is the per-person surname search
    stored = page.evaluate(
        "() => JSON.parse(localStorage.getItem('apexNewStarts.WE 9.13.ids')||'{}')")
    assert "aundre browder" not in stored
    assert "cristian amaya vega" not in stored


ROSTER_NO_LINKS = """
<!doctype html><html><body>
<!-- a stray Filter box OUTSIDE the grid: counting inputs in document order
     puts the surname in the wrong column, which is what happened live -->
<input placeholder="Filter" id="stray">
<table>
<thead><tr><th>First Name</th><th>Last Name</th><th>User Name</th><th></th></tr>
<tr><td><input placeholder="Filter" id="ffirst"></td>
    <td><input placeholder="Filter" id="lf"></td>
    <td><input placeholder="Filter"></td>
    <td><button id="apply">Apply Filters</button></td></tr></thead>
<tbody id="rows"></tbody></table>
</body></html>
"""

ROSTER_SLOW_REPAINT = """() => {
  /* Apex repaints AFTER Apply Filters comes back. Until it does, the previous
     person's rows are still what is on screen -- the live page showed
     "Russell" typed in the filter with Rosa Capel listed underneath. */
  const btn = document.getElementById('apply');
  const slow = btn.cloneNode(true);       /* drops the immediate listener */
  btn.replaceWith(slow);
  slow.addEventListener('click', () => setTimeout(window.__render, 1800));
}"""


ROSTER_NO_LINKS_WIRING = """() => {
  /* Apex's real roster: Edit is a BUTTON that routes in JavaScript. There is
     not one /employees/ href anywhere on the page. */
  const all = [['Rosa', 'Capel', '3001'], ['Kalynn', 'Nugent', '9999']];
  window.__render = () => {
    const want = document.getElementById('lf').value.toLowerCase();
    /* With NO filter this shows only the first row, the way page 1 of a
       paginated roster does. Anything that judges presence after the filter is
       cleared will decide almost everybody is missing. */
    const shown = want ? all.filter(r => r[1].toLowerCase().includes(want))
                       : all.slice(1, 2);
    document.getElementById('rows').innerHTML = shown
      .map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>x</td>
        <td><button class="ed" data-id="${r[2]}">Edit</button></td></tr>`).join('');
    document.querySelectorAll('.ed').forEach(b =>
      b.addEventListener('click', () => {
        window.__clicked = b.dataset.id;
        /* a file:// origin refuses pushState to another path, so the URL half
           cannot be simulated here -- what matters is that the RIGHT row's
           Edit was the thing clicked */
        try { history.pushState({}, '',
          '/employees/' + b.dataset.id + '/edit/employment-record'); } catch (e) {}
      }));
  };
  document.getElementById('apply').addEventListener('click', window.__render);
  document.getElementById('lf').value = 'nugent';      /* wrong page to start */
  window.__render();
}"""


def test_it_opens_people_by_clicking_edit_not_by_reading_links(page, tmp_path):
    """The harvest looked for <a href="/employees/123">Edit</a>. Apex's roster
    has NO such link -- not one in the whole page -- so every person came back
    "not found" while sitting right there on screen. Filter to them, click
    their Edit, and read where the app lands."""
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_NO_LINKS)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_NO_LINKS_WIRING)
    page.evaluate("() => localStorage.clear()")

    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])

    # the panel starts its own lookup; let that settle before driving directly
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.includes('found')",
        timeout=20000)
    page.evaluate("() => { window.__clicked = null; }")
    page.evaluate(
        "async () => await window.__ansOpen({name:'Rosa Capel', find:'Capel'})")

    assert page.evaluate("() => window.__clicked") == "3001", \
        "it filtered to Rosa and clicked HER Edit, not Kalynn's"


def test_it_names_who_it_could_not_find_and_offers_a_retry(page, tmp_path):
    """"5 not on the Pending tab" says there is a problem and nothing about
    which five, so nobody can act on it. Name them, and give a way to look
    again once they have been added in Apex."""
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_NO_LINKS)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_NO_LINKS_WIRING)
    page.evaluate("() => localStorage.clear()")

    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {}},
              {"name": "Nobody Here", "find": "Here", "pages": {}},
              {"name": "Also Missing", "find": "Missing", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfind").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.includes('Pending tab')",
        timeout=25000)

    out = page.locator("#ansout").inner_text()
    assert "Nobody Here" in out and "Also Missing" in out
    assert "Rosa Capel" not in out, "the one it found is not listed as missing"
    assert page.locator("#ansagain").count() == 1, "and a way to look again"


def test_packets_no_longer_open_tabs_at_all(page, tmp_path):
    """First they opened 23 tabs, then one shared tab -- and both still meant
    searching Blue Ink and hunting for Quick View. Now the document loads in a
    pane beside the table, so nothing opens a tab."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {}},
              {"name": "Tyler Ketchum", "find": "Ketchum", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.evaluate("() => { window.open = () => null; }")   # no real tabs in a test
    page.locator("#ansrun").click()

    links = page.locator("#anssetup [data-doc]")
    assert links.count() == 2
    for i in range(2):
        assert links.nth(i).get_attribute("target") is None, \
            "it loads in the pane, it does not open a tab"


def test_the_header_says_where_you_are(page, tmp_path):
    """On the roster, naming one person reads as though the button is about to
    do only them -- and that is exactly where the whole-week run is started
    from."""
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Cristian Amaya Vega", "find": "Vega", "pages": {}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]

    roster = tmp_path / "roster.html"; roster.write_text(ROSTER_NO_LINKS)
    page.goto(roster.as_uri())
    page.evaluate(js)
    head = page.locator("#anspanel").inner_text()
    assert "Ready to run" in head and "2 new starts" in head
    assert "Aundre Browder" not in head, "no single name on the roster"

    person = tmp_path / "user-profile.html"; person.write_text("<h1>profile</h1>")
    page.goto(person.as_uri())
    page.evaluate(js)
    head = page.locator("#anspanel").inner_text()
    assert "Aundre Browder" in head and "1 of 2" in head


def test_the_packet_opens_beside_the_social_box(page, tmp_path):
    """Searching Blue Ink, opening the envelope and finding Quick View, for
    each of 23 people, is the slow part. The document and the box to type into
    belong on one screen (Megan, 2026-09-10)."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {},
               "doc": "https://example.invalid/rosa-w4.pdf"},
              {"name": "No Packet", "find": "Packet", "pages": {}, "doc": ""}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansrun").click()

    assert page.locator("#ansdoc").count() == 1, "a pane for the document"
    page.locator('[data-doc="0"]').click()
    assert page.locator("#ansdoc").get_attribute("src") == \
        "https://example.invalid/rosa-w4.pdf"
    assert "Rosa Capel" in page.locator("#ansdocname").inner_text()
    assert page.evaluate(
        "() => document.activeElement.getAttribute('data-s')") == "0", \
        "and the cursor lands in HER Social box"


def test_somebody_with_no_packet_says_so_rather_than_blanking(page, tmp_path):
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    people = [{"name": "No Packet", "find": "Packet", "pages": {}, "doc": ""}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansrun").click()
    page.locator('[data-doc="0"]').click()
    out = page.locator("#ansdocname").inner_text()
    assert "no signed packet" in out


def test_the_roster_panel_offers_only_the_run(page, tmp_path):
    """"Just this page" and "Saved -> next" are about ONE person. On the
    roster they are clutter you have to think about and then dismiss."""
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]

    roster = tmp_path / "roster.html"; roster.write_text(ROSTER_NO_LINKS)
    page.goto(roster.as_uri())
    page.evaluate(js)
    assert page.locator("#ansrun").count() == 1
    assert not page.locator("#ansfill").is_visible()
    assert not page.locator("#ansnext").is_visible()
    assert "Ready to run" in page.locator("#anshead").inner_text()
    assert "Aundre" not in page.locator("#anshead").inner_text()

    person = tmp_path / "user-profile.html"; person.write_text("<h1>profile</h1>")
    page.goto(person.as_uri())
    page.evaluate(js)
    assert page.locator("#ansfill").is_visible(), "still there on a record"
    assert page.locator("#ansnext").is_visible()
    assert "Aundre Browder" in page.locator("#anshead").inner_text()


def test_the_header_stops_naming_somebody_once_the_screen_moves(page, tmp_path):
    """The panel is built once and Apex never reloads, so anything decided at
    build time goes stale. It sat on the roster headed "Cristian Amaya Vega ·
    2 of 23" while the line under it was looking up number 4."""
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Rosa Capel", "find": "Capel", "pages": {}}]
    person = tmp_path / "user-profile.html"; person.write_text("<h1>profile</h1>")
    page.goto(person.as_uri())
    page.evaluate("() => localStorage.clear()")
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    assert "Aundre Browder" in page.locator("#anshead").inner_text()

    # the run moves back to the list -- in the real app without a reload
    page.evaluate("""() => {
      const t = document.createElement('div');
      t.innerHTML = `<table><thead>
        <tr><th>First Name</th><th>Last Name</th></tr>
        <tr><td><input placeholder="Filter"></td>
            <td><input placeholder="Filter"></td></tr></thead></table>`;
      document.body.appendChild(t);
    }""")
    page.wait_for_function(
        "() => document.getElementById('anshead').innerText.includes('Ready')",
        timeout=5000)
    assert "Aundre" not in page.locator("#anshead").inner_text()
    assert not page.locator("#ansfill").is_visible()


def test_a_late_repaint_does_not_lose_somebody(page, tmp_path):
    """Reading the rows on a fixed timer read the PREVIOUS person's rows and
    wrote the current one down as absent -- four people came back "not on the
    Pending tab" who were each one repaint away (Megan, 2026-09-10)."""
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_NO_LINKS)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_NO_LINKS_WIRING)
    page.evaluate(ROSTER_SLOW_REPAINT)
    page.evaluate("() => localStorage.clear()")

    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansfind").click()
    page.wait_for_function(
        "() => /found|Pending tab/.test(document.getElementById('ansout').innerText)",
        timeout=25000)

    out = page.locator("#ansout").inner_text()
    assert "Pending tab" not in out, out
    assert "All 1 found" in out


ROSTER_BOTH_BOXES = """(names) => {
  /* A roster that honours BOTH filter boxes, the way Apex's does. */
  window.__render = () => {
    const l = document.getElementById('lf').value.toLowerCase();
    const f = document.getElementById('ffirst').value.toLowerCase();
    const shown = names.filter(r => (!l || r[1].toLowerCase().includes(l)) &&
                                    (!f || r[0].toLowerCase().includes(f)));
    document.getElementById('rows').innerHTML = shown
      .map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>x</td>
        <td><button class="ed" data-id="${r[2]}">Edit</button></td></tr>`).join('');
    document.querySelectorAll('.ed').forEach(b =>
      b.addEventListener('click', () => { window.__clicked = b.dataset.id; }));
  };
  document.getElementById('apply').addEventListener('click', window.__render);
  window.__render();
}"""


def _roster(page, tmp_path, names):
    f = tmp_path / "roster.html"
    f.write_text(ROSTER_NO_LINKS)
    page.goto(f.as_uri())
    page.evaluate(ROSTER_BOTH_BOXES, names)
    page.evaluate("() => localStorage.clear()")


def test_it_types_the_first_name_too(page, tmp_path):
    """Megan, 2026-09-10: "you should be typing in first and last to get
    exact". Filtering on the surname alone hands back everyone who shares
    it and leaves the right row to be guessed at."""
    _roster(page, tmp_path, [["Xzavier", "Russell", "7001"],
                             ["Dana", "Russell", "7002"]])
    people = [{"name": "Xzavier Russell", "find": "Russell", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.evaluate("""async () => await window.__ansOpen(
        {name:'Xzavier Russell', find:'Russell'})""")

    assert page.evaluate(
        "() => document.getElementById('ffirst').value").lower() == "xzavier"
    assert page.evaluate("() => window.__clicked") == "7001", "his row, not Dana's"


def test_a_different_name_in_apex_is_reported_not_guessed(page, tmp_path):
    """If Apex holds a different first name -- a nickname, or a middle name in
    the box -- the surname on its own would leave one row and it is tempting
    to take it. It is not taken: filling a stranger's record with somebody
    else's date of birth and Social is far worse than saying "not found"."""
    _roster(page, tmp_path, [["Terry", "Dandy", "7100"]])
    people = [{"name": "Terrance Dandy", "find": "Dandy", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.evaluate("""async () => await window.__ansOpen(
        {name:'Terrance Dandy', find:'Dandy'})""")

    assert page.evaluate("() => window.__clicked") is None, \
        "it did not open somebody else's record"

    page.locator("#ansfind").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.includes('Pending tab')",
        timeout=25000)
    assert "Terrance Dandy" in page.locator("#ansout").inner_text()


# ---------------------------------------------------------------------------
# The loader. Megan, 2026-09-10: "can't you just give me a link to click each
# time so I don't have to keep resaving this over and over". The bookmark is
# now a stub that carries nothing; every fix and every week rides in on the
# paste that was already a weekly step.
# ---------------------------------------------------------------------------

def _stub_host(page, tmp_path, name="host.html"):
    """Serve the stub the way it is really served -- inside an href -- and
    hand back what a click would actually run, entities and all."""
    host = tmp_path / name
    host.write_text('<a id="bm" href="'
                    + filler.build_stub().replace('"', "&quot;")
                    + '">Fill Apex</a><div id="apexish">roster</div>')
    page.goto(host.as_uri())
    return page.locator("#bm").get_attribute("href")[len("javascript:"):]


def test_the_stub_asks_for_a_setup_when_it_has_none(page, tmp_path):
    js = _stub_host(page, tmp_path)
    page.evaluate("() => localStorage.clear()")
    page.evaluate(js)
    assert page.locator("#ansload").count() == 1
    assert page.locator("#anspanel").count() == 0, "nothing to run yet"


def test_a_pasted_setup_runs_and_is_remembered(page, tmp_path):
    """The whole point: paste once, and the bookmark keeps working after."""
    js = _stub_host(page, tmp_path)
    page.evaluate("() => localStorage.clear()")
    page.evaluate(js)

    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}}]
    page.fill("#ansblob",
              filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansloadgo").click()
    assert page.locator("#anspanel").count() == 1, "it ran what was pasted"
    assert page.locator("#ansload").count() == 0

    # click the bookmark again: no paste box, it runs from what it kept
    page.evaluate(js)
    assert page.locator("#anspanel").count() == 1
    assert page.locator("#ansload").count() == 0


def test_load_a_new_setup_hands_back_to_the_loader(page, tmp_path):
    """How a fix reaches somebody now -- the bookmark never changes."""
    js = _stub_host(page, tmp_path)
    page.evaluate("() => localStorage.clear()")
    page.evaluate(js)
    page.fill("#ansblob", filler.build_js(
        [{"name": "Aundre Browder", "find": "Browder", "pages": {}}],
        "WE 9.13")[len("javascript:"):])
    page.locator("#ansloadgo").click()

    page.locator("#ansnew").click()
    assert page.locator("#ansload").count() == 1, "the paste box is back"
    assert page.evaluate(
        "() => localStorage.getItem('apexNewStarts.code')") is None


def test_the_setup_survives_the_page_it_is_copied_from(page, tmp_path):
    """End to end through the REAL page: whatever the copy box hands over has
    to still be runnable JavaScript. Escaping "<" before "&" turns "&lt;" into
    "&amp;lt;" and the browser hands back the wrong characters -- the same
    class of bug as the apostrophe that once killed the button outright."""
    people = [{"name": "Aundre Browder", "find": "Browder", "hire": "9/8/2026",
               "pages": {"employment": {"Position": "Sales Rep"}}}]
    doc = tmp_path / "page.html"
    doc.write_text(filler.build_page(people, "WE 9.13", "September 10, 2026"))
    page.goto(doc.as_uri())
    setup = page.evaluate("() => document.getElementById('thedata').value")

    js = _stub_host(page, tmp_path, "apexish.html")
    page.evaluate("() => localStorage.clear()")
    page.evaluate(js)
    page.fill("#ansblob", setup)
    page.locator("#ansloadgo").click()

    assert page.locator("#anspanel").count() == 1, \
        "the setup copied off the page is still runnable"
    assert "Aundre Browder" in page.locator("#anspanel").inner_text()


def test_a_short_paste_is_refused_rather_than_stored(page, tmp_path):
    js = _stub_host(page, tmp_path)
    page.evaluate("() => localStorage.clear()")
    page.evaluate(js)
    page.fill("#ansblob", "hello")
    page.locator("#ansloadgo").click()
    assert "not the setup" in page.locator("#ansloadmsg").inner_text()
    assert page.evaluate(
        "() => localStorage.getItem('apexNewStarts.code')") is None


# ---------------------------------------------------------------------------
# Security Roles. Megan, 2026-09-10: "it's not checking sales rep so page 1
# isn't saving on the run". Apex refuses the save with "At least one role must
# be assigned", and every role in the list is followed by a "?" help icon.
# ---------------------------------------------------------------------------

ROLES_WITH_HELP_ICONS = """
<!doctype html><html><body>
<h3>Security Roles *</h3>
<div class="roles">
  <div class="radio"><input type="radio" name="role" id="r1" style="display:none">
    <label for="r1">Office Admin <span class="help">?</span></label></div>
  <div class="radio"><input type="radio" name="role" id="r2" style="display:none">
    <label for="r2">ICD Payroll Admin <span class="help">?</span></label></div>
  <div class="radio"><input type="radio" name="role" id="r3" style="display:none">
    <label for="r3">Sales Rep <span class="help">?</span></label></div>
  <div class="radio"><input type="radio" name="role" id="r4" style="display:none">
    <label for="r4">Owner <span class="help">?</span></label></div>
</div>
</body></html>
"""


def test_the_help_icon_does_not_stop_sales_rep_being_ticked(page, tmp_path):
    """An exact match on the label text matched nothing, because the label
    reads "Sales Rep ?" -- so no role was ever assigned and Apex refused to
    save page 1."""
    f = tmp_path / "employment-record.html"
    f.write_text(ROLES_WITH_HELP_ICONS)
    page.goto(f.as_uri())
    page.evaluate(filler.build_js(
        [{"name": "Aundre Browder", "find": "Browder", "pages": {}}],
        "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.length > 0",
        timeout=10000)

    assert page.evaluate("() => document.getElementById('r3').checked"), \
        "Sales Rep is ticked"
    for other in ("r1", "r2", "r4"):
        assert not page.evaluate(
            f"() => document.getElementById('{other}').checked"), \
            f"{other} was left alone"


def test_a_role_that_will_not_tick_is_reported(page, tmp_path):
    """Silence here is what let it reach a run: nothing said the role was
    missing until Apex refused the save."""
    f = tmp_path / "employment-record.html"
    # a real Apex form -- one field it CAN fill -- but no Sales Rep to tick
    f.write_text("<label for='p'>Position</label>"
                 "<input id='p'><h3>Security Roles *</h3><div>Office Admin</div>")
    page.goto(f.as_uri())
    page.evaluate(filler.build_js(
        [{"name": "Aundre Browder", "find": "Browder",
          "pages": {"employment": {"Position": "Sales Rep"}}}],
        "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.length > 0",
        timeout=10000)
    assert "Sales Rep role" in page.locator("#ansout").inner_text()


def test_a_page_with_no_roles_section_does_not_nag(page, tmp_path):
    """The profile and tax tabs have no Security Roles, and saying it is
    missing there would be noise."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>User Profile</h1><label for='g'>Gender</label>"
                 "<select id='g'><option>Female</option></select>")
    page.goto(f.as_uri())
    page.evaluate(filler.build_js(
        [{"name": "Aundre Browder", "find": "Browder", "pages": {}}],
        "WE 9.13")[len("javascript:"):])
    page.locator("#ansfill").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.length > 0",
        timeout=10000)
    assert "Sales Rep role" not in page.locator("#ansout").inner_text()


def test_answers_come_back_into_the_setup_form(page, tmp_path):
    """Megan, 2026-09-10: "I just entered in every social and gender and it
    wiped them all out when we restarted it". They were still in memory --
    the form simply drew itself empty, which is indistinguishable from having
    lost them, and means retyping nineteen of each."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Rosa Capel", "find": "Capel", "pages": {}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]
    page.evaluate(js)

    page.locator("#ansrun").click()
    page.fill('[data-s="0"]', "123456789")
    page.select_option('[data-g="0"]', "Female")
    page.fill('[data-s="1"]', "987654321")
    page.select_option('[data-g="1"]', "Male")
    page.locator("#anscancel").click()      # stopped, for whatever reason

    page.evaluate(js)                        # ...and started again
    page.locator("#ansrun").click()
    assert page.input_value('[data-s="0"]') == "123456789"
    assert page.input_value('[data-s="1"]') == "987654321"
    assert page.input_value('[data-g="0"]') == "Female"
    assert page.input_value('[data-g="1"]') == "Male"


def test_a_gender_survives_the_page_being_reloaded(page, tmp_path):
    """A gender is not a secret and is a chore to re-answer, so it is kept.
    A Social is neither kept nor written down -- it goes with the tab."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]
    page.evaluate(js)
    page.locator("#ansrun").click()
    page.select_option('[data-g="0"]', "Male")
    page.fill('[data-s="0"]', "123456789")
    page.locator("#ansgo").click()

    page.reload()
    page.evaluate(js)
    page.locator("#ansrun").click()
    assert page.input_value('[data-g="0"]') == "Male", "the gender came back"
    assert page.input_value('[data-s="0"]') == "", "the Social did not"

    stored = page.evaluate("() => JSON.stringify(localStorage)")
    assert "123456789" not in stored, "and it is nowhere on disk"


def test_just_this_page_uses_the_answers_already_given(page, tmp_path):
    """Megan, 2026-09-10: "I had to click to go to the 2nd page here and now
    gender doesn't fill again", then "social also not filling in". The setup
    form held both -- only the whole-week run was reading them, so landing on
    a tab by hand and pressing "Just this page" left the required fields empty
    and Apex refused the save."""
    prof = tmp_path / "user-profile.html"
    prof.write_text("<h1>Employee Profile</h1>"
                    "<label for='g'>Gender</label>"
                    "<select id='g'><option></option><option>Female</option>"
                    "<option>Male</option></select>")
    page.goto(prof.as_uri())
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Rosa Capel", "find": "Capel", "pages": {"profile": {}}}]
    js = filler.build_js(people, "WE 9.13")[len("javascript:"):]
    page.evaluate(js)
    page.evaluate("""() => { window.__ansGender['rosa capel'] = 'Female';
                             window.__ansSSN['rosa capel'] = '123456789'; }""")
    page.evaluate(js)                     # reopen, as a click would
    page.locator("#ansfill").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.includes('Filled')",
        timeout=10000)
    assert page.input_value("#g") == "Female"

    tax = tmp_path / "bank-info.html"
    tax.write_text("<h1>Tax</h1><label for='s1'>SSN</label><input id='s1'>"
                   "<label for='s2'>Confirm SSN</label><input id='s2'>")
    page.goto(tax.as_uri())
    page.evaluate(js)
    page.evaluate("""() => { window.__ansSSN['rosa capel'] = '123456789'; }""")
    page.evaluate(js)
    page.locator("#ansfill").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.length > 0",
        timeout=10000)
    assert page.input_value("#s1") == "123456789"
    assert page.input_value("#s2") == "123456789"


def test_the_same_social_twice_is_caught_before_the_run(page, tmp_path):
    """Megan, 2026-09-10: "there should also be some kind of alert here if any
    of the socials are the exact same since we can't see them". The boxes are
    masked, so a slip is invisible. Names are shown; the number never is."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Rosa Capel", "find": "Capel", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansrun").click()
    page.fill('[data-s="0"]', "123456789")
    page.fill('[data-s="1"]', "123456789")

    warn = page.locator("#anssnwarn").inner_text()
    assert "Aundre Browder" in warn and "Rosa Capel" in warn
    assert "123456789" not in warn, "it never shows the number"

    started = []
    page.on("dialog", lambda d: (started.append(d.message), d.dismiss()))
    page.locator("#ansgo").click()
    assert started and "Aundre Browder" in started[0]
    assert page.locator("#anssetup").count() == 1, "the run did not start"


def test_a_half_typed_social_is_caught_too(page, tmp_path):
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    page.evaluate("() => localStorage.clear()")
    page.evaluate(filler.build_js(
        [{"name": "Aundre Browder", "find": "Browder", "pages": {}}],
        "WE 9.13")[len("javascript:"):])
    page.locator("#ansrun").click()
    page.fill('[data-s="0"]', "12345")
    assert "Not nine digits" in page.locator("#anssnwarn").inner_text()


def test_the_run_does_not_search_the_list_twice(page, tmp_path):
    """Megan, 2026-09-10: "it's now searching for these names before AND after
    the info is entered". The pre-sweep filtered to all nineteen and then the
    run filtered to each of them again -- and it could never save that second
    lookup, because it only remembers an id when the row carries an
    /employees/ link and Apex's roster has none."""
    js = filler.build_js([{"name": "Rosa Capel", "find": "Capel", "pages": {}}],
                         "WE 9.13")
    assert "findEveryone(say)" not in js.split("ansgo")[-1], \
        "the run must not sweep the list before it starts"
    assert "ansfind" in js, "the on-demand check is still offered"


def test_try_one_person_needs_only_that_one_row(page, tmp_path):
    """Megan, 2026-09-10: "it's really annoying that I have to fill in all the
    info for us to test and it fails on the first one. It's a waste of time".
    A check should cost one row, not nineteen."""
    f = tmp_path / "user-profile.html"
    f.write_text("<h1>x</h1>")
    page.goto(f.as_uri())
    page.evaluate("() => localStorage.clear()")
    people = [{"name": "Aundre Browder", "find": "Browder", "pages": {}},
              {"name": "Rosa Capel", "find": "Capel", "pages": {}},
              {"name": "Jene Cotton", "find": "Cotton", "pages": {}}]
    page.evaluate(filler.build_js(people, "WE 9.13")[len("javascript:"):])
    page.locator("#ansrun").click()

    # only row 1 answered; the rest deliberately left empty
    page.fill('[data-s="0"]', "123456789")
    page.select_option('[data-g="0"]', "Female")
    assert page.locator("#anssnwarn").inner_text() == "", \
        "leaving the others blank is not an error"

    page.locator("#anstest").click()
    page.wait_for_function(
        "() => document.getElementById('ansout').innerText.length > 0",
        timeout=15000)
    out = page.locator("#ansout").inner_text()
    assert "Aundre Browder" in out
    assert "Rosa Capel" not in out and "Jene Cotton" not in out, \
        "it stopped after the one"
