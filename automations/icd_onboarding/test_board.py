"""The board's rules, which are mostly about what it must NOT do.

Every one of these exists because the thing it forbids would quietly lose work
somebody did by hand, or quietly put a terminated person back on a list that
ends in a payroll record.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B

MONDAY = dt.date(2026, 11, 2)


def _cal(*names):
    return [{"first_name": n.split()[0], "last_name": " ".join(n.split()[1:]),
             "email": n.split()[0].lower() + "@example.com", "phone": "5550100001"}
            for n in names]


# ------------------------------------------------------------- seeding

def test_the_seed_fills_identity_and_nothing_else():
    """Every other column belongs to the automation that owns that step.
    Writing a blank here would be this module claiming to know something."""
    rows = B.seed_rows(_cal("Ada Fournier"), started=MONDAY)
    assert rows[0]["Name"] == "Ada" and rows[0]["Last Name"] == "Fournier"
    assert rows[0]["Start"] == "11/02/2026"
    for col in B.TICKS:
        assert col not in rows[0], "%s is not the seed's to write" % col
    assert B.BY_HAND not in rows[0]


def test_a_second_seed_adds_newcomers_and_rewrites_nobody():
    """Somebody's hand-typed cell is worth more than a tidy re-seed."""
    existing = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0],
                     **{"Blue Ink": "✓", "Final Status": ""})]
    got = B.merge(existing, B.seed_rows(_cal("Ada Fournier", "Bruno Castell"), MONDAY))
    assert [r["Name"] for r in got["add"]] == ["Bruno"]
    assert got["keep"] == 1


def test_somebody_the_icd_marked_off_does_not_come_back():
    """The calendar will go on saying they showed up for training. The board
    is the only thing that knows they left -- that is why it exists."""
    gone = dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0],
                **{B.BY_HAND: B.TERMINATED})
    got = B.merge([gone], B.seed_rows(_cal("Ada Fournier"), MONDAY))
    assert got["add"] == [], "they were marked off; the seed must not re-add them"
    assert got["left"] == [B.person_key(gone)]


def test_people_are_matched_on_email_not_spelling():
    a = B.seed_rows(_cal("Esme Vance"), MONDAY)[0]
    b = dict(a, Name="Esmé", **{"Last Name": "Vance-Hale"})
    assert B.person_key(a) == B.person_key(b)


# --------------------------------------------------------- hide, never delete

def test_terminated_rows_are_hidden_not_dropped():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0]),
            dict(B.seed_rows(_cal("Bruno Castell"), MONDAY)[0],
                 **{B.BY_HAND: B.TERMINATED})]
    assert [r["Name"] for r in B.visible(rows)] == ["Ada"]
    assert [r["Name"] for r in B.visible(rows, show_terminated=True)] == ["Ada", "Bruno"]
    assert len(rows) == 2, "the row itself is still there"


# ------------------------------------------------------------- ticks go on

def test_a_tick_is_never_taken_off():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0], **{"Blue Ink": "✓"}),
            dict(B.seed_rows(_cal("Bruno Castell"), MONDAY)[0])]
    plan = B.tick_plan(rows, "Blue Ink", ["Bruno Castell"])
    assert plan == [1], "only the untouched one"
    assert B.tick_plan(rows, "Blue Ink", []) == [], "nobody named = nothing cleared"


def test_an_already_ticked_row_is_not_rewritten():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0], **{"Digi Docs": "✓"})]
    assert B.tick_plan(rows, "Digi Docs", ["Ada Fournier"]) == []


def test_final_status_is_not_a_machine_column():
    """It is the ICD's, and it is the one signal AppStream cannot give us."""
    rows = B.seed_rows(_cal("Ada Fournier"), MONDAY)
    with pytest.raises(ValueError, match="not a column a machine may write"):
        B.tick_plan(rows, B.BY_HAND, ["Ada Fournier"])
    assert B.BY_HAND not in B.TICKS


def test_the_identity_columns_are_not_tickable_either():
    rows = B.seed_rows(_cal("Ada Fournier"), MONDAY)
    for col in ("Name", "Email", "Start"):
        with pytest.raises(ValueError):
            B.tick_plan(rows, col, ["Ada Fournier"])


# ------------------------------------------------------------------ the week

def test_the_tab_is_named_for_the_monday_whichever_day_is_given():
    assert B.tab_name(dt.date(2026, 11, 8)) == "Week of 11.02"
    assert B.tab_name(dt.date(2026, 11, 2)) == "Week of 11.02"


def test_the_columns_come_from_the_real_obcl():
    for col in ("Contact Added", "BG Status", "Digi Docs", "Onboarding Quizzes",
                "Blue Ink", "Headshot Photo", "UID Request", "Owner Submit",
                "Added to APEX"):
        assert col in B.COLUMNS
