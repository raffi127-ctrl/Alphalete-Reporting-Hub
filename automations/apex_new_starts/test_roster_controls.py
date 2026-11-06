"""Finding the two controls the "add the missing ones" path depends on.

Both were matched on their text being EXACTLY 'all employees' / 'add employee'.
Apex does not render them that way: the roster tabs carry a count, the labels
sit in nested spans, and the Add control is '+ Add Employee'. So the match
failed, `existsAnywhere` returned null, and clicking "Add these N in Apex" did
nothing except say it could not check -- the whole feature, dead on arrival
(Megan, 2026-10-02: "The adding the people to apex if they aren't in pending
isn't working").

Nothing here asserts how Apex is built. It asserts that a handful of plausible
renderings of the SAME two controls are all found, because the previous version
only worked for one of them and we cannot see the real page from here.
"""
from __future__ import annotations

import pytest

from automations.apex_new_starts import filler

pytest.importorskip("patchright.sync_api")

PEOPLE = [{"name": "Aundre Browder", "fields": {"First Name": "Aundre"}}]

# A roster as the app plausibly draws one: a <ul> of tabs whose <li> text is
# the label PLUS a count, the label itself in a span, and the Add control with
# a leading plus and an icon.
ROSTER = """
<!doctype html><html><body>
<div class="toolbar">
  <button id="addbtn"><i class="k-icon k-i-plus"></i> <span>Add Employee</span></button>
</div>
<ul class="k-tabstrip-items">
  <li id="t1"><a href="#"><span>Pending</span> <span class="badge">13</span></a></li>
  <li id="t2"><a href="#"><span>All Employees</span> <span class="badge">482</span></a></li>
  <li id="t3"><a href="#"><span>Terminated</span> <span class="badge">91</span></a></li>
</ul>
<table><tr><th>First Name</th><th>Last Name</th></tr>
<tr><td><input id="ff"></td><td><input id="fl"></td></tr></table>
</body></html>
"""


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


def _load(pg, html):
    pg.set_content(html)
    pg.evaluate(filler.build_js(PEOPLE, "WE 9.13")[len("javascript:"):])


def test_the_all_employees_tab_is_found_through_its_count_badge(page):
    _load(page, ROSTER)
    found = page.evaluate("(function(){var e=window.__ansRoster.tab();"
                          "return e?e.closest('li').id:null})()")
    assert found == "t2", "a count beside the label used to lose the tab"


def test_it_does_not_settle_for_the_pending_tab(page):
    _load(page, ROSTER)
    got = page.evaluate("(function(){var e=window.__ansRoster.tab();"
                        "return e?e.textContent.toLowerCase():''})()")
    assert "all employees" in got
    assert "pending" not in got


def test_the_add_control_is_found_behind_a_plus_and_an_icon(page):
    _load(page, ROSTER)
    found = page.evaluate("(function(){var e=window.__ansRoster.add();"
                          "return e?e.closest('button').id:null})()")
    assert found == "addbtn"


@pytest.mark.parametrize("label", [
    "Add Employee", "+ Add Employee", "Add New Employee", "ADD EMPLOYEE",
])
def test_every_wording_of_the_add_control_still_matches(page, label):
    _load(page, "<button id='addbtn'>%s</button>"
                "<ul><li><a>All Employees 482</a></li></ul>" % label)
    assert page.evaluate("(function(){var e=window.__ansRoster.add();"
                         "return e?e.closest('button').id:null})()") == "addbtn"


def test_the_panels_own_buttons_are_never_mistaken_for_apexs(page):
    """The panel says things like "Add these 2 in Apex". Matching our own UI
    would make the run click itself."""
    _load(page, ROSTER)
    page.evaluate("document.getElementById('anspanel').insertAdjacentHTML("
                  "'beforeend','<button id=\"mine\">Add Employee</button>')")
    assert page.evaluate("(function(){var e=window.__ansRoster.add();"
                         "return e?e.id:null})()") != "mine"


def test_a_hidden_tab_is_not_clicked(page):
    _load(page, "<ul><li id='h' style='display:none'><a>All Employees</a></li>"
                "<li id='v'><a>All Employees 482</a></li></ul>")
    found = page.evaluate("(function(){var e=window.__ansRoster.tab();"
                          "return e?e.closest('li').id:null})()")
    assert found == "v"


def test_a_page_with_no_tab_says_what_it_did_offer(page):
    """The old failure said only that it could not check, which is the same
    sentence for every cause and answerable from none of them."""
    _load(page, "<button>Save</button><a href='#'>Reports</a>")
    assert page.evaluate("window.__ansRoster.tab()") is None
    labels = page.evaluate("window.__ansRoster.labels()")
    assert "save" in labels and "reports" in labels
