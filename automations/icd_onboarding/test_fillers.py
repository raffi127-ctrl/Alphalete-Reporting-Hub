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
    assert list(got) == ["Digi Docs"]
    assert list(got["Digi Docs"]) == ["Ada Fournier"]


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
    assert list(got["Blue Ink"]) == ["Esme Vance Hale"]


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


def test_a_status_lands_as_its_own_words_not_a_date():
    """Megan, 2026-11-09: "We should just have Background Status: xStatus"."""
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "sterling", {"Ada Fournier": {"BG Status": "Passed"}})
    assert got == {"BG Status": {"Ada Fournier": "Passed"}}


def test_a_plain_yes_still_lands_as_a_date():
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "blueink", {"Ada Fournier": {"Blue Ink": True}})
    written = got["Blue Ink"]["Ada Fournier"]
    assert written.count("/") == 2, "a tick is a date: %r" % written


# ------------------------------- ticking from the job that does the thing

def test_a_single_column_source_can_tick_by_name(monkeypatch):
    """The contact sync knows WHO it just added; it should not have to build a
    verdict dict to say so."""
    seen = {}

    def fake_apply(book, week, source, verdicts, **kw):
        seen.update({"source": source, "verdicts": verdicts, "dry": kw.get("dry_run")})
        return 0

    monkeypatch.setattr(F, "apply", fake_apply)
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    F.tick("raf", MONDAY, "contacts", ["Ada Fournier", "Bruno Castell"],
           log=lambda *a: None)
    assert seen["verdicts"] == {"Ada Fournier": {"Contact Added": True},
                                "Bruno Castell": {"Contact Added": True}}
    assert seen["dry"] is True, "dry unless asked"


def test_a_multi_column_source_must_say_which(monkeypatch):
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    with pytest.raises(ValueError, match="owns 5 columns"):
        F.tick("raf", MONDAY, "ownerville", ["Ada Fournier"], log=lambda *a: None)


def test_an_office_with_no_board_is_reported_not_silently_skipped(monkeypatch):
    said = []
    monkeypatch.setattr(F, "workbook_for",
                        lambda k: (_ for _ in ()).throw(RuntimeError("no office %r" % k)))
    n = F.tick("nowhere", MONDAY, "contacts", ["Ada Fournier"], log=said.append)
    assert n == 0
    assert any("nowhere" in s for s in said), "a silent miss is a tick nobody notices"


def test_raf_resolves_even_though_he_has_no_metrics_workbook():
    import inspect
    src = inspect.getsource(F.workbook_for)
    assert "ALL_IN_ONE_RAF" in src, "Alphalete is not an ICD and has no metrics book"
# ------------------------------------------- which OwnerVille programme

def test_the_ov_programme_is_per_office_not_alphaletes():
    """ICDs are in different programmes (Megan, 2026-11-09). RES-AT&T is
    Alphalete's, and inheriting it for an ICD reads an empty table — which
    looks exactly like nobody having done anything."""
    import inspect
    from automations.obcl_ov_sweep import ov_table
    assert "campaign" in inspect.signature(ov_table.read_table).parameters
    from automations.office_admin import config as OC
    assert hasattr(OC.Office("k", "o", "1"), "ov_program")
    assert OC.office("raf").ov_program == "RES-AT&T"


def test_an_office_with_no_programme_set_does_not_inherit_alphaletes():
    from automations.office_admin import config as OC
    assert OC.office("omar").ov_program == "", (
        "blank until somebody says which — a guess here reads an empty table")


def test_a_programme_ownerville_does_not_have_fails_loudly():
    """Selecting a campaign that is not in the dropdown selects nothing, and
    the table then reads empty. That must raise, not return no rows."""
    import inspect
    from automations.obcl_ov_sweep import ov_table
    src = inspect.getsource(ov_table.read_table)
    assert "has no %r programme" in src
    assert "It offers:" in src
