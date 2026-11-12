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
