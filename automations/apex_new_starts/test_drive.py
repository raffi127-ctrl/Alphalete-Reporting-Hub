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
