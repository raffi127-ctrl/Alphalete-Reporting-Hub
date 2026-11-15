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
    """A page that answers the roster search the way Apex does.

    It reports itself AS A ROSTER (triage refuses to decide anything from a
    page that is not one), remembers which tab was clicked, and answers the
    filter search from the sets it was given.
    """

    url = "https://apex.example/roster"

    def __init__(self, pending=(), anywhere=(), raises=None, says=None,
                 no_search=False, no_tab=False):
        self.pending = set(pending)
        self.anywhere = set(anywhere)
        self.raises = raises or set()
        self.says = says or {}
        self.no_search, self.no_tab = no_search, no_tab
        self.tab, self.looked_for, self._marking = "Pending", "", "Pending"

    # --- what the driver does to it ------------------------------------
    def locator(self, sel):
        """Playwright's locator, enough of it: .first.click()."""
        page = self

        class _Loc:
            @property
            def first(self):
                return self

            def click(self, timeout=None):
                page.click(sel, timeout=timeout)

        return _Loc()

    def click(self, sel, timeout=None):
        if "data-ans-apply" in sel:
            return
        if "data-ans-tabmark" in sel:
            if self.no_tab:
                raise RuntimeError("no such tab")
            self.tab = self._marking
            return

    def fill(self, sel, val):
        pass

    def type(self, sel, val, delay=None):
        if "last" in sel:
            self.looked_for = val

    def press(self, sel, key):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg=None):
        if "All Employees" in js and "innerText" in js:      # on_roster
            return True
        if "data-ans-tabmark" in js:                         # finding a tab
            self._marking = arg
            return "" if self.no_tab else "li"
        if "data-ans-apply" in js:                           # finding Apply
            return "" if self.no_search else "ok"
        if "data-ans-f" in js:                               # the filter boxes
            return {} if self.no_search else {"last": True, "first": True}
        if "includes(want)" in js:                           # the row count
            who = self.anywhere if self.tab == "All Employees" else self.pending
            if self.looked_for in self.says:
                return 0
            return sum(1 for n in who
                       if self.looked_for.lower() in n.lower())
        name = (arg or {}).get("name", "")
        if name in self.raises:
            raise RuntimeError("the page gave up")
        if "__ansOpen" in js:
            return "id-%s" % name if name in self.pending else ""
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
    """A search that could not be run is not a search that found nobody.
    Taking it as "not in Apex" would create a second record for a real
    employee."""
    page = _Triage(no_search=True)
    got = drive.triage(page, [{"name": "X Y"}], log=lambda *a: None)
    assert got["X Y"]["need"] == drive.BY_HAND
    assert "UNKNOWN" in got["X Y"]["why"]
    assert "could not be run" in got["X Y"]["why"]


def test_a_lookup_that_throws_is_by_hand_not_a_create():
    page = _Triage(no_tab=True)
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


class _Secret(_Tabs):
    """A page whose Social boxes answer only a character COUNT -- which is
    all a masked box will tell anybody."""

    def __init__(self, holds=9, **kw):
        super().__init__(**kw)
        self.holds = holds

    def evaluate(self, js, arg=None):
        if "best = Math.max" in js:
            return self.holds
        return super().evaluate(js, arg)


def test_a_social_on_the_tax_tab_is_typed_and_never_logged():
    page = _Secret(holds=9, typed="123456789")
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


def test_a_box_holding_the_wrong_value_is_not_a_success():
    """Rate of Pay reported filled showing $10.10 for somebody whose rate is
    $10.00 (2026-11-12). Anything non-empty counted, so a wrong number on a
    payroll record passed -- the one failure nobody would ever see."""
    assert drive.same_value("10.00", "$10.00")
    assert not drive.same_value("10.00", "$10.10")
    assert not drive.same_value("10.00", "")
    # decoration is fine; a different value is not
    assert drive.same_value("4000.00", "$4,000.00")
    assert drive.same_value("512-743-2199", "512-743-2199")
    assert drive.same_value("Jenniferleegreen.jg@gmail.com",
                            "jenniferleegreen.jg@gmail.com")
    assert not drive.same_value("Green", "Greene")


def test_typing_clears_the_box_before_it_types():
    """`fill("")` does not empty a Kendo numeric box -- it reformats -- so the
    new keystrokes landed on top of the old value. That is where $10.10 came
    from: $10.00 was already in there."""
    import inspect
    src = inspect.getsource(drive.type_into)
    assert 'page.fill("[data-ans-type=' not in src, "fill does not clear these"
    assert "Meta+a" in src and "Delete" in src, "select all, then delete"
    assert src.index("Delete") < src.index("page.type("), "clear BEFORE typing"


def test_moving_between_tabs_falls_back_to_a_real_click():
    """goSpa clicks the tab anchor from inside the page. That works from the
    roster but not from ON a record, where the tab strip is wired up and this
    rewrite ignores untrusted events -- so the walk stopped dead after the
    employment tab."""
    import inspect
    src = inspect.getsource(drive.go_tab)
    assert "data-ans-tab" in src
    assert src.index("__ansGoSpa") < src.index('[data-ans-tab]", timeout'), \
        "try the page's own navigation first, then click it for real"


def test_a_tab_is_reached_only_by_clicking_its_link():
    """Measured on the live site, 2026-11-12 (probe_nav):

      * there is no Angular on a record at all, so the ui-sref on each tab
        link has no handler and the link is a plain anchor
      * a driver click on it navigates every time, on a clean form
      * a DIRECT navigation is refused: the server answers 302 and sends the
        session to its change-password page

    So the click is the only way, and both location.assign and page.goto are
    dead ends that were each tried and each bounced."""
    import inspect
    body = inspect.getsource(drive.go_tab).split('"""', 2)[-1]
    code = [l for l in body.splitlines() if not l.strip().startswith("#")]
    assert any("[data-ans-tab]" in l for l in code), "click the link"
    for dead in ("page.goto", "location.assign"):
        assert not any(dead in l for l in code), "%s is bounced by Apex" % dead


def test_the_unsaved_changes_confirm_is_always_dismissed():
    """Apex raises a confirm() when a tab with unsaved typing is left. The
    dialog has to be DISMISSED: accepting it navigates away and throws the
    fill on the floor (probe_dirty, 2026-11-12)."""
    import inspect
    src = inspect.getsource(drive.guard_unsaved)
    assert "d.dismiss()" in src
    assert "d.accept()" not in src, "accepting discards what was typed"
    walk = inspect.getsource(drive.complete_person)
    assert walk.index("guard_unsaved(") < walk.index("for tab, path, prove")


def test_no_tab_is_left_behind_an_unsaved_one():
    """Each tab must be saved before the next opens -- the next one is behind
    the confirm, and the only way through it discards this one. So a walk
    with nothing to save fills ONE tab and stops, rather than carrying on and
    losing the work."""
    import inspect
    src = inspect.getsource(drive.complete_person)
    assert "if save is None:" in src
    assert src.index("if save is None:") < src.index('bool(save(tab, got))')
    assert "cannot be opened until" in src, "and it says why it stopped"


def test_a_save_is_watched_for_not_asked_for():
    """A POST to the employee's own URL IS the save -- a direct observation,
    not a guess from a page that looks different afterwards. And not a
    keypress in a terminal: that was the first version, and a step somebody
    cannot find is a step that does not work."""
    import inspect
    src = inspect.getsource(drive.wait_for_save)
    assert 'want in (res.url or "")' in src
    assert "GET" in src, "a GET is not a save"
    assert "input()" not in src, "nothing waits on a keyboard"


# ------------------------------------------------- pressing Save by machine

class _Saver:
    """A page that records the Save click and can refuse to post."""

    def __init__(self, *, found="Save", post=True, objects=()):
        self.found, self.post, self.objects = found, post, list(objects)
        self.clicks, self.handlers = [], []

    def evaluate(self, js, arg=None):
        if "data-ans-save" in js and "removeAttribute" in js:
            return self.found
        if "validation-summary-errors" in js:
            return self.objects
        return ""

    def on(self, what, fn):
        self.handlers.append((what, fn))

    def remove_listener(self, what, fn):
        pass

    def click(self, sel, timeout=None):
        self.clicks.append(sel)
        if not self.post:
            return
        res = type("R", (), {
            "url": "https://apex.example/employees/42/edit",
            "status": 200,
            "request": type("Q", (), {"method": "POST"})()})()
        for what, fn in self.handlers:
            if what == "response":
                fn(res)

    def wait_for_timeout(self, ms):
        pass


def test_nothing_is_saved_when_a_required_box_has_no_value():
    """Apex would refuse it anyway, and a refused save leaves the form dirty
    -- which blocks every tab after it."""
    page = _Saver()
    said = []
    assert not drive.save_tab(page, 42, {"absent": ["gender"]}, log=said.append)
    assert page.clicks == [], "it must not even press Save"
    assert "gender" in said[0]


def test_nothing_is_saved_when_a_box_holds_the_wrong_value():
    """The $10.10 case. A wrong number on a payroll record is the one outcome
    nobody would ever see was wrong, so it never reaches Save."""
    page = _Saver()
    said = []
    assert not drive.save_tab(page, 42, {"missed": ["Rate of Pay"]}, log=said.append)
    assert page.clicks == []
    assert "Rate of Pay" in said[0]


def test_a_save_is_only_a_save_when_the_post_comes_back():
    """A click that looked fine is not a save. This is the 'green means
    delivered' rule, on a payroll record."""
    page = _Saver(post=False)
    said = []
    assert not drive.save_tab(page, 42, {}, log=said.append, seconds=1)
    assert "nothing was posted" in said[-1]
    assert drive.save_tab(_Saver(post=True), 42, {}, log=lambda *a: None)


def test_apex_objecting_is_not_a_save():
    """A validation failure POSTs too. Calling that a save is exactly the
    mistake that must never pass here."""
    page = _Saver(objects=["Rate of Pay is required."])
    said = []
    assert not drive.save_tab(page, 42, {}, log=said.append)
    assert "Apex objects" in said[-1]


def test_no_save_control_is_reported_not_assumed():
    page = _Saver(found="")
    said = []
    assert not drive.save_tab(page, 42, {}, log=said.append)
    assert "no Save control" in said[0]


def test_every_pick_puts_the_list_away():
    """Country timed out picking 'United States' while a probe that opened
    the same dropdown on its own read `['Canada', 'United States']` straight
    off it -- the exact text. The difference was State being picked
    immediately beforehand, with its popup still on screen covering the next
    widget (2026-11-12). So a pick settles the popups before it opens one and
    after it picks."""
    import inspect
    for fn in (drive.set_dropdown, drive.set_dropdown_by_name):
        src = inspect.getsource(fn)
        body = src.split('"""', 2)[-1]
        first_click = body.index("page.click(")
        assert "settle_popups(page)" in body[:first_click], \
            "%s must clear the last popup before opening one" % fn.__name__
        assert body.count("settle_popups(page)") >= 2, \
            "%s must put its own list away too" % fn.__name__


def test_settling_waits_for_the_popup_to_actually_go():
    """A container mid-animation still swallows a click, so pressing Escape
    is not enough on its own."""
    import inspect
    src = inspect.getsource(drive.settle_popups)
    assert "Escape" in src
    assert "k-animation-container" in src
    assert "offsetParent" in src, "gone means not rendered, not just marked"


def test_marking_a_box_clears_the_previous_widget_mark_too():
    """Only [mark] was cleared, so every earlier [mark-widget] stayed on the
    page and the SECOND pick on a tab matched two elements -- the click then
    failed. That is why Country died straight after State, and why Gender
    being skipped changed nothing (2026-11-12)."""
    import inspect
    src = inspect.getsource(drive._mark_by_name)
    marks = src.split("querySelectorAll(", 1)[1].split(")", 1)[0]
    assert "-widget" in marks, "both marks have to be cleared"
    assert "removeAttribute(mark + '-widget')" in src


def test_the_widget_is_found_above_the_input_as_well():
    """Gender is a Kendo COMBOBOX: its input sits inside a .k-dropdown-wrap,
    so the widget span is a grandparent and looking only at the parent's
    children found nothing -- the click had no target and timed out."""
    import inspect
    src = inspect.getsource(drive._mark_by_name)
    assert "closest(" in src, "walk up, not just across"
    assert "k-combobox" in src, "a combobox is not a .k-dropdown"


def test_a_missing_dropdown_says_so_instead_of_timing_out():
    """'could not pick (TimeoutError)' is what a widget that was never found
    looked like for two runs, and it reads like a slow page."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert "no dropdown around it" in src
    assert src.index("no dropdown around it") < src.index('-widget] .k-select')


def test_filled_is_not_the_same_answer_as_saved():
    """A run that timed out waiting for somebody still printed "filled and
    saved" for that tab (2026-11-13). That is calling an exit code a
    delivery, on a payroll record."""
    import inspect
    src = inspect.getsource(drive.complete_person)
    assert 'got["saved"] = False' in src, "nothing is saved until it is"
    assert 'got["saved"] = bool(save(tab, got))' in src, "record what happened"
    assert src.index('got["saved"] = False') < src.index("if save is None:")


def test_a_combobox_is_opened_by_its_arrow_not_its_wrapper():
    """Every failure on the profile and tax tabs was a name ending in
    `_input` -- Gender_input, MaritalStatus_input, StateToBeTaxedIn_input --
    while the plain ids went in first time (2026-11-13). Those are Kendo
    COMBOBOXES, and the wrapper click that opens a DropDownList does nothing
    to them. filler.py has said so all along: "a combobox takes typing; a
    dropdown list does not"."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert ".k-select" in src, "the arrow is what opens a combobox"
    assert src.index(".k-select") < src.index('("wrapper"'), \
        "try the arrow before the wrapper"


def test_a_list_that_never_opened_is_not_a_click_that_timed_out():
    """'could not pick (TimeoutError)' hid this for three runs: it reads like
    a slow page, not like a control that was never opened. Each way in is
    tried and the one that worked is named in the log."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert "nothing opened its list" in src
    assert "via %s" in src, "the log has to say how it opened"
    # and the row is only clicked once something is actually open
    assert src.index("if not opened:") < src.index("li:text-is(%r)")


def test_the_row_is_clicked_before_anything_is_typed():
    """Megan described what a person actually does: "you have to actually
    click the word in the dropdown" -- a click, with no typing. Typing FIRST
    filters the list, so the row being looked for may no longer be in it,
    which is how Gender opened fine and set nothing three runs running
    (2026-11-13). Typing is the fallback for a list too long to show the row,
    not the opening move."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert "page.type(" not in src, "the picker itself does not type"
    assert "_type_then_pick(" in src, "typing is a fallback it calls"
    assert src.index("li:text-is(%r)") < src.index("_type_then_pick("), \
        "click the word first"
    # and the fallback refuses a box that cannot actually be typed into
    helper = inspect.getsource(drive._type_then_pick)
    assert "b.tagName === 'INPUT'" in helper and "readOnly" in helper


def test_what_a_dropdown_shows_is_read_wherever_it_lives():
    """A DropDownList puts the chosen text in its wrapper; a COMBOBOX keeps it
    in an <input value=...>, which has no innerText -- so the check read ''
    for Gender while the screen plainly said "Not Specified", and a pick that
    worked would have been called a miss."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    read = src.split("shown = page.evaluate", 1)[1][:700]
    assert "'value' in box" in read, "the input's value counts as shown"
    assert "innerText" in read, "and so does the wrapper's text"


def test_the_row_is_clicked_in_the_widgets_own_list():
    """Megan watched it type "male" into Gender and the value still did not
    stick: "it looks like you have to actually click the word in the
    dropdown" (2026-11-13). The click was not raising, so it was landing
    somewhere -- and these pages carry several `ul.k-list`, one per dropdown
    plus the nav. A row clicked in another widget's list throws nothing and
    does nothing, which is exactly what was seen.

    Kendo names the list a widget owns via aria-owns / aria-controls."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert "aria-owns" in src and "aria-controls" in src
    # scoped to that list by id, not to every k-list on the page
    assert '[id=%s] li:text-is(%r)' in src
    # and when there is no aria link, it falls back to the one list actually
    # on screen rather than any k-list anywhere
    assert 'ul.k-list:visible' in src


def test_the_owned_list_is_matched_by_attribute_not_by_hash_id():
    """Apex's aria-owns carries a literal, un-rendered Angular template --
    `StateProvince_{{::$id}}_listbox` -- and Kendo really does create the list
    under that id. Braces and colons are illegal in a CSS #id selector, so
    `#...` threw and broke State and Country, which had been working
    (2026-11-13)."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    assert '[id=%s]' in src, "an attribute selector takes the id as spelled"
    assert '"#%s li' not in src, "a #id selector cannot hold braces or colons"
    assert "json.dumps(owned)" in src, "and it has to be quoted"


def test_a_numeric_spinner_is_never_treated_as_a_dropdown():
    """Kendo gives its numeric textbox `k-widget` too, so "the widget near
    this label" could resolve to Rate of Pay -- and the arrow click that
    opens a list is then the SPIN-UP arrow. That is where $10.10 came from
    for a $10.00 rate: one step of 0.1, twice onto a real payroll record.

    Measured with probe_rate, 2026-11-13: typing the box is flawless (clear,
    1, 10, 10., 10.0, 10.00, blur -> 10.00). The typing was never the bug."""
    import inspect
    for fn in (drive._mark_by_name, drive.set_dropdown):
        src = inspect.getsource(fn)
        assert "spinbutton" in src, \
            "%s must recognise a spinner" % fn.__name__
        assert "k-numerictextbox" in src, \
            "%s must refuse a numeric widget" % fn.__name__


def test_the_rate_is_read_back_after_everything_else():
    """It is the value nobody would see was wrong, and a stray click moves it
    by one step, so it is not trusted from the moment it was typed."""
    import inspect
    src = inspect.getsource(drive.fill_employment)
    assert "DRIFTED" in src
    assert src.index("__ansDoPage") < src.index("DRIFTED"), \
        "check it after the engine has had its turn, not before"
    assert 'miss.append("Rate of Pay")' in src, "and report it as not set"


def test_a_pick_is_never_closed_with_escape():
    """ESCAPE REVERTS A KENDO COMBOBOX. That was the whole Gender bug: the row
    was clicked, the box read `Male`, and then settle_popups pressed Escape
    and put it back to empty -- so the check read '' and called it a miss.

    probe_gender measured it on the live record (2026-11-13): clicking the
    row, ArrowDown+Enter and typing+Enter ALL set the box to `Male`. Every
    one was being undone afterwards. State and Country are DropDownLists,
    which do not revert -- which is why only the three comboboxes ever
    failed."""
    import inspect
    src = inspect.getsource(drive.set_dropdown_by_name)
    after = src.split("li:text-is(%r)", 1)[1]
    assert "close_list(page)" in after, "a pick is closed with a blur"
    # THE SUCCESS PATH ONLY. The failure branch may settle however it likes:
    # there is no pick there to preserve.
    won = after.split("return False", 1)[1]
    reads = won.index("shown = page.evaluate")
    assert "settle_popups(page)" not in won[:reads], \
        "Escape after a pick undoes it"
    assert "close_list(page)" in won[:reads]
    # and close_list really does blur rather than press a key. THE CODE: its
    # docstring says the word "Escape" while explaining why it does not press
    # one, and an explanation of a rule is not a breach of it (third time
    # this has caught me out today).
    helper = inspect.getsource(drive.close_list)
    body = helper.split('"""', 2)[-1]
    code = [l for l in body.splitlines() if not l.strip().startswith("#")]
    assert any("blur" in l for l in code), "it blurs"
    assert not any("Escape" in l for l in code), "and presses no key"


def test_a_masked_box_is_checked_by_count_not_by_value():
    """A masked box shows dots or nothing at all, so the only honest check is
    how many characters it holds. Comparing the dots with what was typed
    called a correct entry WRONG and refused the whole tax tab
    (2026-11-13)."""
    from automations.apex_new_starts.ssn_prompt import Secret
    said = []
    got = drive.fill_tax(_Secret(holds=9), {}, Secret("123456789"),
                         log=said.append)
    assert got["set"] == ["Social"], got
    assert "123456789" not in " ".join(said), said


def test_a_social_one_digit_short_is_refused():
    """Megan watched the Social go in correctly on the first box and ONE
    DIGIT SHORT on the second: the confirm box reformats as you type and
    swallowed a character (2026-11-13). Apex refuses a Social that does not
    match its confirmation, and so does this."""
    from automations.apex_new_starts.ssn_prompt import Secret
    said = []
    got = drive.fill_tax(_Secret(holds=8), {}, Secret("123456789"),
                         log=said.append)
    assert got["missed"] == ["Social"], got
    assert "8 characters, typed 9" in " ".join(said), said
    assert "123456789" not in " ".join(said), said


def test_a_social_is_typed_slowly_enough_not_to_drop_one():
    import inspect
    src = inspect.getsource(drive.type_by_name)
    assert "120 if secret else 30" in src, "a masked box needs the slower type"


def test_a_tab_waits_for_its_whole_form_before_typing():
    """Waiting for ONE field was not enough. Alexandria's employment tab was
    saved after 24 seconds -- fast -- and the profile tab was still being
    built when the fill began: LastName took 'McCrob' instead of 'McCrobie',
    BirthDay came out empty, and Street, City, Zip and Phone reported "no
    box" for boxes that plainly exist (2026-11-14).

    Kyle's run looked fine only because that save took 136 seconds. A race
    that depends on how fast somebody clicks is not a thing to leave in."""
    import inspect
    for fn in (drive.fill_profile, drive.fill_tax):
        src = inspect.getsource(fn)
        assert "wait_for_all_named(" in src, \
            "%s must wait for its whole form" % fn.__name__
        assert src.index("wait_for_all_named(") < src.index("set_, miss"), \
            "%s must wait BEFORE it types" % fn.__name__


def test_arrived_is_not_the_same_as_settled():
    """The form can still be re-bound for a moment after the last box
    appears, which is how two characters went missing off a surname."""
    import inspect
    src = inspect.getsource(drive.wait_for_all_named)
    assert "wait_for_timeout(1200)" in src, "a beat after the last box arrives"
    assert "never arrived" in src, "and it says so when they do not"


class _Roster(_Triage):
    """A roster that can be told whether it looks like one, and holds nobody.

    Everything the driver does to a page -- the tab clicks, the filter typing,
    the Apply click -- comes from _Triage, so these tests exercise the same
    search the real triage runs.
    """

    def __init__(self, *, is_roster=True, drifts=False):
        super().__init__()
        self.is_roster, self.drifts, self.asked = is_roster, drifts, 0

    def evaluate(self, js, arg=None):
        if "All Employees" in js and "innerText" in js:      # on_roster
            self.asked += 1
            if self.drifts and self.asked > 1:
                return False
            return self.is_roster
        if "__ansExistsAnywhere" in js:
            return False
        return super().evaluate(js, arg)


def test_a_lookup_that_could_not_run_is_never_an_absence():
    """On 2026-11-14 the roster came up as Apex's change-password page with
    no nav, so the Pending lookup found nobody and the All-Employees check
    found nobody -- and triage called that "not in Apex at all" for somebody
    whose employment record it had saved twenty minutes earlier.

    Absence routes to the CREATE form, and a create on an existing person is
    a second payroll record for a real employee."""
    page = _Roster(is_roster=False)
    page.wait_for_timeout = lambda ms: None
    said = []
    got = drive.triage(page, [{"name": "Ada Fournier"}], log=said.append)
    assert got["Ada Fournier"]["need"] == drive.BY_HAND, got
    why = got["Ada Fournier"]["why"].lower()
    assert "unknown" in why and "never create" in why, why
    assert "NOT ON THE ROSTER" in " ".join(said)


def test_the_roster_drifting_mid_check_is_not_an_absence_either():
    """It was the roster when we started looking and something else by the
    time we had an answer. That answer proves nothing."""
    page = _Roster(drifts=True)
    page.wait_for_timeout = lambda ms: None
    got = drive.triage(page, [{"name": "Ada Fournier"}], log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.BY_HAND, got
    assert "UNKNOWN" in got["Ada Fournier"]["why"]


def test_a_real_roster_that_really_has_nobody_still_says_add():
    """The guard must not swallow the genuine case: a roster with rows on
    screen, searched properly, that does not hold this person."""
    page = _Roster(is_roster=True)
    page.wait_for_timeout = lambda ms: None
    got = drive.triage(page, [{"name": "Ada Fournier"}], log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.ADD, got


def test_the_roster_is_given_time_to_arrive_before_it_is_judged():
    """on_roster was right to refuse a page it could not read, and wrong to
    ask only once: the first run after it shipped landed on /roster -- the
    right URL -- and checked before the rows had rendered, so a real employee
    came back UNKNOWN and the run stopped (2026-11-15)."""
    import inspect
    src = inspect.getsource(drive.triage)
    assert "wait_for_roster(" in src, "wait, then judge"
    # and the refusal still stands when it genuinely never arrives
    waiter = inspect.getsource(drive.wait_for_roster)
    assert "return False" in waiter


def test_a_roster_that_never_arrives_is_still_refused():
    class _Never(_Roster):
        def evaluate(self, js, arg=None):
            if "All Employees" in js:
                return False
            return ""

    page = _Never()
    page.wait_for_timeout = lambda ms: None
    got = drive.triage(page, [{"name": "Ada Fournier"}], log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.BY_HAND
    assert "UNKNOWN" in got["Ada Fournier"]["why"]


def test_a_slow_roster_is_waited_for_and_then_used():
    class _Slow(_Roster):
        def __init__(self):
            super().__init__()
            self.looks = 0

        def evaluate(self, js, arg=None):
            if "All Employees" in js and "innerText" in js:   # on_roster only
                self.looks += 1
                return self.looks > 3          # arrives on the fourth look
            return _Triage.evaluate(self, js, arg)

    page = _Slow()
    page.wait_for_timeout = lambda ms: None
    got = drive.triage(page, [{"name": "Ada Fournier"}], log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.ADD, got


def test_the_roster_is_recognised_by_its_tabs_not_by_its_rows():
    """Apex's roster shows NO rows until a filter is applied: `tbody tr` is 0
    on a perfectly good page, and the 8 `tr` it has are the headings and the
    filter line (probe_roster, 2026-11-15). Requiring rows made the guard
    refuse the LIVE roster and report a real employee as UNKNOWN.

    The four tabs are rendered DOM, and a page that never loaded has none of
    them -- so this is still "I can see a roster", not "the URL looks
    right"."""
    import inspect
    src = inspect.getsource(drive.on_roster)
    assert "All Employees" in src and "Pending" in src and "Active" in src
    # THE SELECTOR, not the note explaining why there isn't one. The comment
    # names `tbody tr` while saying it is the wrong signal -- an explanation
    # of a rule is not a breach of it (this keeps catching me out).
    code = [l for l in src.splitlines()
            if "querySelectorAll" in l or "querySelector(" in l]
    assert not any("tbody tr" in l for l in code), \
        "rows are not a readiness signal here"
    assert "change your password" in src


def test_the_roster_search_is_run_from_out_here_not_by_the_engine():
    """Apex's roster lists nobody until a filter is applied, and the engine
    applies its filter with an IN-PAGE click, which this rewrite ignores --
    the same untrusted-event problem as the dropdowns. So both lookups
    searched an empty table and a real employee came back "not in Apex at
    all", which routes to the create form (2026-11-15)."""
    import inspect
    src = inspect.getsource(drive.triage)
    assert "search_roster(" in src, "the create guard searches from Python"
    assert "__ansExistsAnywhere" not in src, "the engine cannot apply a filter"
    assert "open_roster_tab(" in src, "and the tab is clicked for real"
    # the PENDING lookup stays with the engine: it is the part that works
    assert "__ansOpen" in src, "the engine finds people on Pending"


def test_a_search_that_could_not_run_is_not_an_empty_result():
    """None is not zero. Returning 0 here would route a real employee to the
    create form and a second payroll record."""
    import inspect
    src = inspect.getsource(drive.search_roster)
    assert "return None" in src
    assert "None is NOT zero" in src, "and it says so where it is written"
    # the caller keeps them apart
    tri = inspect.getsource(drive.triage)
    assert "if there is None:" in tri, "the All Employees search keeps them apart"


def test_both_tabs_are_searched_pending_then_all_employees():
    """"Not on Pending" has never meant "not in Apex", and creating somebody
    already there is a second payroll record for a real employee."""
    page = _Triage(pending=set(), anywhere={"Ada Fournier"})
    got = drive.triage(page, [{"name": "Ada Fournier", "find": "Fournier"}],
                       log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.BY_HAND, got
    assert "not on Pending" in got["Ada Fournier"]["why"]


def test_somebody_the_search_finds_on_pending_is_completed():
    page = _Triage(pending={"Ada Fournier"})
    got = drive.triage(page, [{"name": "Ada Fournier", "find": "Fournier"}],
                       log=lambda *a: None)
    assert got["Ada Fournier"]["need"] == drive.COMPLETE, got
    assert got["Ada Fournier"]["id"] == "id-Ada Fournier"


def test_a_roster_tab_is_clicked_unambiguously():
    """Each tab is an <a> inside an <li>, so a selector naming both matches
    TWO elements and the click is refused for being ambiguous -- which read
    as "could not open the 'Pending' tab" (2026-11-15)."""
    import inspect
    src = inspect.getsource(drive.open_roster_tab)
    assert "data-ans-tabmark" in src, "found in js, clicked by its mark"
    code = [l for l in src.splitlines() if not l.strip().startswith("#")]
    assert not any("text-is" in l for l in code), \
        "playwright text matching would not click these"


def test_apply_filters_is_found_in_js_and_clicked_for_real():
    """The roster lists nobody until Apply Filters is pressed. The button is
    <button ng-click="vm.onChangeFilters()">Apply Filters</button>, and
    Playwright's :text-is() would not click it any more than it would the
    tabs -- Enter does not search either, so the table stayed empty at
    tr=8/tbody=0 before AND after, and every lookup found nobody
    (probe_filter, 2026-11-15)."""
    import inspect
    src = inspect.getsource(drive.search_roster)
    code = [l for l in src.splitlines() if not l.strip().startswith("#")]
    assert any("data-ans-apply" in l for l in code), "marked, then clicked"
    assert any("onchangefilters" in l.lower() for l in code), \
        "its own handler names it when the label does not"
    assert not any("text-is" in l for l in code), "that did not click it"
    # and a page with no Apply control is UNKNOWN, never an empty result
    assert any("return None" in l for l in code)
