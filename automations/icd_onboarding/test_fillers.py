"""What a source may and may not tick.

Each of these is a rule that already exists in one of the automations being
wired up. They are tested here because this is now the one place all five go
through, so a rule lost here is a rule lost everywhere.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F

MONDAY = dt.date(2026, 11, 2)


def _row(name, off="", **steps):
    r = {"Week of": B.week_label(MONDAY), "Name": name.split()[0],
         "Last Name": " ".join(name.split()[1:]), "Classroom": "",
         B.TERMINATED_AT: off}
    for s in B.STEPS:
        r[s] = steps.get(s.replace(" ", "_"), "")
    return r


# --------------------------------------------------------------- on only

def test_only_a_yes_ticks():
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True,
                                                       "UID Request": False}})
    assert got == {"Digi Docs": ["Ada Fournier"]}


def test_unread_is_not_undone():
    """done_columns answers None when it could not read the header. That means
    the page did not load, not that the step is outstanding."""
    rows = [_row("Ada Fournier")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": None}}) == {}


def test_a_no_never_clears_an_existing_tick():
    rows = [_row("Ada Fournier", Digi_Docs="11/03/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": False}}) == {}


def test_an_already_ticked_step_is_not_ticked_again():
    """So running this hourly writes nothing on the hours nothing happened."""
    rows = [_row("Ada Fournier", Digi_Docs="11/03/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True}}) == {}


# ------------------------------------------------- a source stays in its lane

def test_a_source_cannot_tick_somebody_elses_column():
    """Blue Ink has no business touching Owner Submit. A wiring mistake should
    surface here, not as a wrong tick on a real person."""
    rows = [_row("Ada Fournier")]
    with pytest.raises(ValueError, match="may not tick"):
        F.plan(rows, "blueink", {"Ada Fournier": {"Owner Submit": True}})


def test_the_ownerville_columns_are_the_sweeps_own_five():
    from automations.obcl_ov_sweep import config as OV
    assert set(F.SOURCES["ownerville"]) == set(OV.COLUMNS)


def test_every_source_column_is_a_real_board_step():
    for source, cols in F.SOURCES.items():
        for c in cols:
            assert c in B.STEPS, "%s claims %r, which is not a step" % (source, c)


def test_the_five_sources_cover_every_step_exactly_once():
    seen = [c for cols in F.SOURCES.values() for c in cols]
    assert sorted(seen) == sorted(B.STEPS), "every step has exactly one owner"


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError, match="not a source"):
        F.plan([], "guesswork", {})


# ----------------------------------------------------- people who have left

def test_somebody_marked_off_is_never_ticked():
    """They left. Ticking their steps puts them back on the chase list and on
    the printed sheet."""
    rows = [_row("Ada Fournier", off="11/06/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True}}) == {}


def test_somebody_not_on_the_board_is_ignored_quietly():
    """OwnerVille carries the whole office; the board is this week."""
    rows = [_row("Ada Fournier")]
    assert F.plan(rows, "ownerville", {"Someone Else": {"Digi Docs": True}}) == {}


def test_names_are_matched_past_spelling():
    rows = [_row("Esme Vance Hale")]
    got = F.plan(rows, "blueink", {"esme  vance-hale": {"Blue Ink": True}})
    assert got == {"Blue Ink": ["Esme Vance Hale"]}


# ------------------------------------------------------------- the dry run

def test_a_dry_run_names_everybody_it_would_tick():
    """A count on its own cannot be checked against anything."""
    rows = [_row("Ada Fournier"), _row("Bruno Castell")]
    got = F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True},
                                      "Bruno Castell": {"Digi Docs": True}})
    said = F.describe(got)
    assert "Ada Fournier" in said and "Bruno Castell" in said and "Digi Docs" in said


def test_apply_is_dry_by_default():
    import inspect
    assert inspect.signature(F.apply).parameters["dry_run"].default is True
