"""Driving the bookmarklet's own engine from Python.

The engine is proven -- it has been doing Raf's weeks since September. These
pin the SEAM: that we load that code rather than a second copy of it, and that
the two things a person used to type arrive without ever being logged.
"""
from __future__ import annotations

import inspect

from automations.apex_new_starts import drive
from automations.apex_new_starts import filler as F
from automations.apex_new_starts.ssn_prompt import Secret


class _Page:
    """A page that only records what it was asked to evaluate."""

    def __init__(self):
        self.calls = []

    def evaluate(self, js, arg=None):
        self.calls.append((js, arg))
        return []


def test_the_whole_of_one_person_is_an_entry_point():
    """runPerson walks the three tabs, saves each and reads Status back. It was
    the only part of the engine NOT on window, so a driven page could reach
    doPage and openPerson but had to re-assemble the loop in Python -- which is
    exactly how two fillers came to disagree about one form."""
    assert "window.__ansRunPerson=runPerson;" in F._JS


def test_the_engine_is_loaded_not_reimplemented():
    """If this module ever grows its own form-filling, the two copies drift and
    the drift lands on a real employee's record."""
    src = inspect.getsource(drive)
    assert "F._JS" in src, "the script must come from filler.py"
    for invented in ("querySelector('[ng-model", "k-datepicker", "roleID"):
        assert invented not in src, "drive.py is filling forms itself: %s" % invented


def test_a_social_reaches_the_page_and_nothing_else():
    said = []
    page = _Page()
    got = drive.hand_over(page, genders={"Ada Fournier": "Female"},
                          socials={"Ada Fournier": Secret("123456789")},
                          log=lambda m: said.append(m))
    assert got == {"genders": 1, "socials": 1}
    # it went into the page...
    js, arg = page.calls[-1]
    assert "__ansSSN" in js and arg[1] == {"Ada Fournier": "123456789"}
    # ...and nowhere else. The log says how many, never which or what.
    assert "123456789" not in " ".join(said), said
    assert "Ada" not in " ".join(said), said


def test_a_social_that_is_not_nine_digits_is_dropped():
    """A short one would be typed into a payroll record and Apex would take
    it. Better to leave the box empty and have the run say it is missing."""
    page = _Page()
    got = drive.hand_over(page, socials={"Ada Fournier": Secret("1234")},
                          log=lambda *a: None)
    assert got["socials"] == 0
    assert page.calls[-1][1][1] == {}


def test_a_social_is_revealed_in_exactly_one_place():
    """Secret exists so a Social cannot be printed by accident. The wrapper is
    worth nothing if reveal() is scattered."""
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(drive.__file__).read_text(encoding="utf-8"))
    # the CALLS, not the word -- a docstring that explains the rule is not a
    # second place a Social gets revealed.
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "reveal"]
    assert len(calls) == 1, "one call site, at the moment it is typed"


def test_a_blank_gender_is_not_handed_over_as_a_guess():
    """Nothing guesses a gender: the value lands on a payroll record."""
    page = _Page()
    got = drive.hand_over(page, genders={"Ada Fournier": "", "Dev Rao": "Male"},
                          log=lambda *a: None)
    assert got["genders"] == 1
    assert page.calls[-1][1][0] == {"Dev Rao": "Male"}


# ------------------------------- which of the two each person actually needs

class _Triage:
    """A page that answers the two lookups from a script it was given."""

    def __init__(self, pending=(), anywhere=(), raises=None, says=None):
        self.pending = set(pending)
        self.anywhere = set(anywhere)
        self.raises = raises or set()
        self.says = says or {}

    def evaluate(self, js, arg=None):
        name = (arg or {}).get("name", "")
        if name in self.raises:
            raise RuntimeError("the page gave up")
        if "__ansOpen" in js:
            return "id-%s" % name if name in self.pending else ""
        if "__ansExistsAnywhere" in js:
            if name in self.says:
                return self.says[name]          # a string: could not tell
            return name in self.anywhere
        return None


def test_somebody_on_pending_is_completed_not_created():
    """Megan, 2026-11-11: "know if they need added or if they just need the
    user profile completed because they're already on the pending". Both
    checks this week landed on somebody already there."""
    page = _Triage(pending={"Victoria Newsom"})
    got = drive.triage(page, [{"name": "Victoria Newsom"}], log=lambda *a: None)
    assert got["Victoria Newsom"]["need"] == drive.COMPLETE


def test_somebody_apex_has_never_heard_of_is_created():
    page = _Triage()
    got = drive.triage(page, [{"name": "New Person"}], log=lambda *a: None)
    assert got["New Person"]["need"] == drive.ADD


def test_in_apex_but_not_on_pending_goes_to_a_person():
    """Creating them duplicates a real payroll record; completing them has
    nowhere to start. Neither is safe, so it is named instead."""
    page = _Triage(anywhere={"Old Hand"})
    got = drive.triage(page, [{"name": "Old Hand"}], log=lambda *a: None)
    assert got["Old Hand"]["need"] == drive.BY_HAND
    assert "not on Pending" in got["Old Hand"]["why"]


def test_could_not_tell_is_never_read_as_not_there():
    """The engine returns a STRING when it cannot read All Employees. Taking
    that as "not in Apex" would create a second record for a real employee."""
    page = _Triage(says={"X Y": "no All Employees tab on this page"})
    got = drive.triage(page, [{"name": "X Y"}], log=lambda *a: None)
    assert got["X Y"]["need"] == drive.BY_HAND
    assert "All Employees" in got["X Y"]["why"]


def test_a_lookup_that_throws_is_by_hand_not_a_create():
    page = _Triage(raises={"X Y"})
    got = drive.triage(page, [{"name": "X Y"}], log=lambda *a: None)
    assert got["X Y"]["need"] == drive.BY_HAND


def test_a_whole_week_is_sorted_into_the_three():
    page = _Triage(pending={"On Pending"}, anywhere={"Elsewhere In"})
    got = drive.triage(page, [{"name": "On Pending"}, {"name": "Elsewhere In"},
                              {"name": "Brand New"}], log=lambda *a: None)
    assert got["On Pending"]["need"] == drive.COMPLETE
    assert got["Elsewhere In"]["need"] == drive.BY_HAND
    assert got["Brand New"]["need"] == drive.ADD


def test_the_roster_is_reached_through_the_app_not_the_address_bar():
    """Every signed-in Apex session lands on the change-password page, which
    has no roster on it: a triage run straight from there was told the page
    offers "log off, support, feedback" and refused everybody (2026-11-11).
    A page.goto redirects back to that page, so this has to go through the
    app's own router."""
    import inspect
    src = inspect.getsource(drive.to_roster)
    assert "__ansGoSpa" in src
    # the CODE, not the docstring that explains why -- a comment naming the
    # thing we must not do is not the thing being done.
    body = src.split(chr(34) * 3, 2)[-1]
    assert "goto" not in body, "a typed URL bounces back to change-password"


def test_a_roster_that_cannot_be_reached_is_not_a_week_with_nobody_in_apex():
    class _P:
        url = "https://apex.example/Identity/Account/Manage/ChangePassword"
        def evaluate(self, *a, **k):
            return False
    assert drive.to_roster(_P(), log=lambda *a: None) is False


def test_every_entry_point_the_drivers_call_is_listed():
    """ENTRY_POINTS is what `ready` checks before anything runs. One missing
    from the list reads as Apex refusing something, rather than as a script
    that half-loaded."""
    from automations.apex_new_starts import filler as F
    for name in drive.ENTRY_POINTS:
        assert "window.%s=" % name in F._JS, name


def test_the_triage_keeps_the_apex_id_for_the_complete_path():
    """Completing somebody means going to /employees/<id>/edit/... . The
    first rehearsal threw the id away, called doPage on whatever page was
    showing -- the roster -- and filled nothing at all (2026-11-11)."""
    page = _Triage(pending={"Victoria Newsom"})
    got = drive.triage(page, [{"name": "Victoria Newsom"}], log=lambda *a: None)
    assert got["Victoria Newsom"]["id"] == "id-Victoria Newsom"


def test_the_engine_is_put_back_after_a_full_page_load():
    """Crossing from Apex's Identity page into the app is a real link, so
    everything on window goes with it. The first complete rehearsal reached
    the roster, lost the engine on the way, and could not open anybody's
    record (2026-11-11)."""
    calls = {"evals": 0}

    class _P:
        def __init__(self):
            self.loaded = False
        def evaluate(self, js, arg=None):
            calls["evals"] += 1
            if "filter(n => typeof window[n]" in js:
                return list(drive.ENTRY_POINTS) if self.loaded else []
            self.loaded = True       # the script body ran
            return None

    page = _P()
    assert drive.keep_loaded(page, [{"name": "X"}], "11/08/2026",
                             log=lambda *a: None) is True


def test_keep_loaded_does_nothing_when_the_engine_is_already_there():
    class _P:
        def evaluate(self, js, arg=None):
            assert "filter(n => typeof window[n]" in js, "it must not re-run the script"
            return list(drive.ENTRY_POINTS)
    assert drive.keep_loaded(_P(), log=lambda *a: None) is True


# --------------------------------------------------- the other two tabs
# Profile and tax are driven by field NAME, because Apex mislabels its own
# tax fields and gives the two Social boxes no label at all. These pin the
# three things that would go wrong silently.

class _Tabs:
    """A page that answers the by-name driver, and records every click."""

    def __init__(self, *, shown="", typed="", pw_on=False):
        self.clicks, self.typed_into, self.shown, self.value = [], [], shown, typed
        self.pw_on = pw_on

    def evaluate(self, js, arg=None):
        if "data-ans-pw" in js and "override" in js.lower():
            return "ON" if self.pw_on else "already off"
        if "data-ans-pw" in js:
            return self.pw_on
        # removeAttribute FIRST: _mark_by_name's own script mentions
        # '.k-widget')' in passing, so a widget-shaped test matches it too.
        if "removeAttribute" in js:
            return "visible"
        if "-widget']" in js or "-widget')" in js:
            return self.shown
        if "e.value" in js:
            return self.value
        return ""

    def click(self, sel, timeout=None):
        self.clicks.append(sel)
        if sel == "[data-ans-pw]":
            self.pw_on = False

    def fill(self, sel, val):
        pass

    def type(self, sel, val, delay=None):
        self.typed_into.append((sel, val))

    def wait_for_timeout(self, ms):
        pass


def test_every_field_on_those_two_tabs_is_covered():
    """A key in filler.PAGE_OF that no map here carries is a value that gets
    built, previewed, and then quietly never typed."""
    for page in ("profile", "tax"):
        missing = [k for k in F.PAGE_OF[page] if k not in drive.FILLS]
        assert not missing, "%s tab does not fill %s" % (page, missing)


def test_claim_dependants_goes_by_label_with_apex_s_own_spelling():
    """It has no name attribute, and Apex refuses the tax tab without it. A
    'Claim Dependents' with an E matches nothing and reports nothing."""
    assert dict(drive.TAX_BY_LABEL) == {"Claim Dependants": "claim_dependents"}


def test_the_password_email_tick_is_unticked_with_a_real_click():
    """box.click() from JavaScript is untrusted, and this rewrite ignores
    untrusted events -- so the old JS untick would report success while the
    tick stayed on and the save emailed a real person their password."""
    page = _Tabs(pw_on=True)
    said = []
    drive.password_email_off(page, log=said.append)
    assert page.clicks == ["[data-ans-pw]"], page.clicks
    assert "now off" in said[0], said


def test_a_tick_that_will_not_come_off_says_do_not_save():
    """Silence here is the dangerous answer: the operator is about to press
    Save themselves."""
    page = _Tabs(pw_on=True)
    page.evaluate = lambda js, arg=None: (  # noqa: E731 — stays ON throughout
        "ON" if "override" in js.lower() else True)
    said = []
    drive.password_email_off(page, log=said.append)
    assert "do not save" in said[-1], said


def test_the_profile_tab_always_ends_by_unticking_the_password_email():
    """Last, and unconditionally. An early return that skips it is how it
    leaked in production from September."""
    src = inspect.getsource(drive.fill_profile)
    body = src.split("for name, key in PROFILE_TEXT")[1]
    assert "password_email_off(page, log=log)" in body
    # the untick, then one return. A return between them is the leak.
    before, after = body.split("password_email_off(page, log=log)")
    assert "return" not in before, "nothing may return before the untick"
    assert after.count("return") == 1, after


def test_a_social_on_the_tax_tab_is_typed_and_never_logged():
    page = _Tabs(typed="123456789")
    said = []
    got = drive.fill_tax(page, {}, Secret("123456789"), log=said.append)
    assert got["set"] == ["Social"], got
    assert "123456789" not in " ".join(said), said
    # both boxes, every time: Apex refuses the tab when they disagree
    assert [v for _s, v in page.typed_into] == ["123456789", "123456789"]


def test_no_social_means_no_social_box_is_touched():
    """The rehearsal reads Blue Ink with keep_ssn=False, so there is nothing
    to type -- and an empty Social typed into a payroll record is worse than
    a blank one."""
    page = _Tabs()
    got = drive.fill_tax(page, {}, None, log=lambda *a: None)
    assert page.typed_into == []
    assert "Social" not in got["set"] + got["missed"]
