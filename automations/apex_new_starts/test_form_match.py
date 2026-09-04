"""Does the field finder actually land on the right box?

`apex.find_field` locates each value by the LABEL a person reads beside it,
because nobody could reach a logged-in Apex screen while this was written. That
makes the label list the riskiest thing in the module: get a wording wrong and
the run either skips the person (loud, fine) or types into the neighbouring box
(silent, and it ends up on a payroll record).

So the ADD ROSTER EMPLOYEE screen is rebuilt here as a fixture from Megan's
screenshots of the WHOLE form (2026-09-03) -- every label in the order it
appears, including the traps that screen actually contains:

  * 'First Name' / 'Middle Name' / 'Last Name' all end in 'Name', and
    'User Name' does too.
  * 'Account Email' is matched by the label of the password-reset CHECKBOX too,
    which reads '...password reset to their Account Email'.
  * 'State Working In' is where they work; the employee's own record has a home
    address with its own state. Matching either on a bare 'state' crosses them.
  * 'Salary' sits right under 'Rate of Pay' and is the wrong box for $10/hr.

WHAT THIS PROVES, AND WHAT IT DOESN'T. It proves the matcher and the label list
agree with the wordings on that screen. It does NOT prove Apex's real markup
ties its labels to its inputs the way this fixture does -- only --explore on the
live page can settle that. When it can, replace this fixture with the structure
`apex_screen.json` reports.
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
  Send this user a password reset to their Account Email. If unchecked, you
  will set the user's password manually.</label>

<h2>Employment Record</h2>
<h3>Alphalete Marketing Inc. &ndash; Arlington</h3>
<span>Status *</span><button id="status">Pending</button>
<label for="f7">Hire Date *</label><input id="f7" name="HireDate" placeholder="MM/dd/yyyy">
<span>Office *</span><div>Rafael Hidalgo - Alphalete Marketing Inc. , Arlington</div>
<label for="f9">Pay Frequency *</label>
  <select id="f9"><option>Select</option><option>Weekly</option></select>
<label for="f10">Position *</label>
  <select id="f10"><option>Select</option><option>Sales Rep</option></select>
<label for="f13">Basis of Pay *</label>
  <select id="f13"><option>Select</option><option>Commissions</option></select>
<label for="f12">State Working In *</label>
  <select id="f12"><option>Select</option><option>Texas</option></select>
<label for="f11">Rate of Pay *</label><input id="f11" type="number">
<label for="f14">Department *</label>
  <select id="f14"><option>Select</option><option>100 Owner</option>
  <option>200 Admin</option><option>400 Sales</option>
  <option>750 Chips</option><option>900 1099</option></select>
<label for="f15">Salary</label><input id="f15" type="number">
<label for="f16"><input type="checkbox" id="f16" checked> Time Clock</label>
<label for="f17"><input type="checkbox" id="f17" checked> Require Break</label>
<span>Divisions</span><div id="divisions">General</div>

<h2>Security Roles *</h2>
<label for="r1"><input type="radio" name="role" id="r1"> Office Admin</label>
<label for="r2"><input type="radio" name="role" id="r2"> ICD Payroll Admin</label>
<label for="r3"><input type="radio" name="role" id="r3"> Sales Rep</label>
<label for="r4"><input type="radio" name="role" id="r4"> Owner</label>
<h2>Module Admin</h2>
</body></html>
"""

# What the run actually fills. 'Office' and 'Status' are NOT here: they are
# pre-filled text on the real form, not inputs.
STAGE_ONE = ("first", "middle", "last", "username", "account_email",
             "hire_date", "pay_frequency", "position", "rate", "pay_state",
             "pay_basis", "department")

EXPECTED_ID = {
    "first": "f1", "middle": "f2", "last": "f3", "username": "f4",
    "account_email": "f5", "hire_date": "f7", "pay_frequency": "f9",
    "position": "f10", "rate": "f11", "pay_state": "f12", "pay_basis": "f13",
    "department": "f14",
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


def test_rate_of_pay_is_not_salary(page):
    """They sit one under the other and both take a number. $10/hr into the
    Salary box is a $10 salary."""
    assert AX.find_field(page, "rate")["id"] == "f11"


def test_state_working_in_is_not_a_home_address(page):
    """Texas is where they WORK. Their address, on a later page, has its own
    state and can say anything -- matching both on a bare 'state' crosses two
    different facts."""
    assert AX.find_field(page, "pay_state")["id"] == "f12"


def test_nothing_the_run_fills_touches_a_leave_alone_box(page):
    """Office, Status, Salary, Time Clock, Require Break and Divisions are all
    correct as the form loads them. The fill must not land on any of them."""
    from automations.apex_new_starts import run as RUN
    values = dict.fromkeys(STAGE_ONE, "x")
    matched, _ = AX.plan_fill(page, values)
    landed = {m[2]["id"] for m in matched}
    assert landed.isdisjoint({"f15", "f16", "f17", "status", "divisions"}), landed


def test_the_security_role_radios_are_never_typed_into(page):
    """The role is TICKED by set_security_role, never typed. Radios sit in
    NON_TEXT_TYPES so the ordinary fill cannot reach one even if a caller
    passed the role in among the values."""
    matched, _ = AX.plan_fill(page, {"security_role": "Sales Rep"})
    assert matched == []


def test_the_password_reset_checkbox_is_left_alone(page):
    """It is ticked by default and mails a real new hire. Nothing in the fill
    plan may touch it -- the operator sees it and decides."""
    values = dict.fromkeys(STAGE_ONE, "x")
    matched, _ = AX.plan_fill(page, values)
    assert "f6" not in {m[2]["id"] for m in matched}
    assert page.locator("#f6").is_checked()


def test_required_is_what_this_screen_actually_asks_for(page):
    """REQUIRED once listed address/city/state/zip/dob. None of those boxes
    exist on this form, so every person came back 'missing required field' and
    nothing would ever have been typed."""
    matched, _ = AX.plan_fill(page, dict.fromkeys(AX.REQUIRED, "x"))
    assert {m[0] for m in matched} == set(AX.REQUIRED)
    assert not ({"address1", "city", "zip", "dob"} & set(AX.REQUIRED))


def test_the_security_role_lands_on_sales_rep(page):
    """Megan, 2026-09-03: Sales Rep. Radios, so it is ticked by its own
    function -- the ordinary fill can never reach one."""
    for r in ("r1", "r2", "r3", "r4"):
        page.locator(f"#{r}").evaluate("el => el.checked = false")
    assert AX.set_security_role(page) is True
    assert page.locator("#r3").is_checked()
    assert not any(page.locator(f"#{r}").is_checked() for r in ("r1", "r2", "r4"))


def test_an_unknown_role_ticks_nothing_at_all(page):
    """The options are Office Admin, ICD Payroll Admin, Sales Rep and Owner. A
    name that isn't one of them must tick NOTHING -- the difference between
    Sales Rep and ICD Payroll Admin is the difference between somebody seeing
    their own numbers and seeing everyone's."""
    for r in ("r1", "r2", "r3", "r4"):
        page.locator(f"#{r}").evaluate("el => el.checked = false")
    assert AX.set_security_role(page, "Admin") is False
    assert not any(page.locator(f"#{r}").is_checked()
                   for r in ("r1", "r2", "r3", "r4"))


def test_every_default_actually_selects_its_option(page):
    """The office settings all land in SELECTs, and a select is not typed into
    -- apply_fill has to pick the option. '400 Sales' is the whole option text,
    number included; picking '400' or 'Sales' would select nothing at all."""
    matched, unmatched = AX.plan_fill(page, dict(AX.DEFAULTS))
    assert not unmatched, unmatched
    AX.apply_fill(page, matched, log=lambda *_: None)
    assert page.locator("#f14").input_value() == "400 Sales"
    assert page.locator("#f10").input_value() == "Sales Rep"
    assert page.locator("#f9").input_value() == "Weekly"
    assert page.locator("#f12").input_value() == "Texas"
    assert page.locator("#f13").input_value() == "Commissions"
    assert page.locator("#f11").input_value() == "10.00"
    assert page.locator("#f15").input_value() == ""      # Salary untouched


def test_nothing_on_stage_one_is_unanswered_now(page):
    """Nothing is unanswered any more. Gender was the last one, and Megan
    answered it by adding a column to the board rather than leaving the run to
    infer it."""
    assert AX.UNANSWERED == ()
