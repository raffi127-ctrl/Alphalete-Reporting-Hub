"""Per-office bundle choices — what it refuses, and why."""
from __future__ import annotations

import pytest

from automations.digi_docs import config as C
from automations.digi_docs import office_config as OC

HEAD = ["Office", "State", "City", "Owner", OC.COL_CAMPAIGN,
        OC.COL_BUNDLE_TYPE, OC.COL_BUNDLE, OC.COL_COMMISSION]


def _rows(monkeypatch, rows):
    monkeypatch.setattr(OC, "_rows", lambda book=None: rows)


def _row(office, campaign="RES-AT&T", btype="Base (Retail)", bundle="",
         commission="Retail Comp Grid"):
    return {"Office": office, "State": "TX", "City": "Plano", "Owner": "X",
            OC.COL_CAMPAIGN: campaign, OC.COL_BUNDLE_TYPE: btype,
            OC.COL_BUNDLE: bundle, OC.COL_COMMISSION: commission}


# ------------------------------------------------- the refusal that matters

def test_an_office_nobody_asked_is_refused_not_defaulted(monkeypatch):
    """Falling back to Alphalete's bundle is the exact failure this prevents:
    a different contract, mailed to a real person, before anybody notices."""
    _rows(monkeypatch, [])
    with pytest.raises(OC.NotAnswered):
        OC.for_office("omar")


def test_a_half_answered_office_is_refused_and_named(monkeypatch):
    _rows(monkeypatch, [_row("omar", btype="", commission="")])
    with pytest.raises(OC.NotAnswered) as e:
        OC.for_office("omar")
    assert OC.COL_BUNDLE_TYPE in str(e.value)
    assert OC.COL_COMMISSION in str(e.value)


def test_the_refusal_never_leaks_alphaletes_answers(monkeypatch):
    _rows(monkeypatch, [])
    try:
        OC.for_office("omar")
    except OC.NotAnswered as e:
        assert C.BUNDLE not in str(e)
        assert C.BUNDLE_TYPE not in str(e)


def test_answered_is_false_rather_than_raising(monkeypatch):
    _rows(monkeypatch, [])
    assert OC.answered("omar") is False


# ------------------------------------------------------- alphalete's own row

def test_alphalete_is_the_constants_because_they_were_written_for_it():
    got = OC.for_office(OC.HOUSE)
    assert got.campaign == C.ADD_CAMPAIGN
    assert got.bundle_type == C.BUNDLE_TYPE
    assert got.bundle == C.BUNDLE
    assert got.commission == tuple(C.COMMISSION_BUNDLES_TICK)


def test_alphalete_needs_no_sheet_row(monkeypatch):
    _rows(monkeypatch, [])
    assert OC.answered(OC.HOUSE) is True


# ------------------------------------------------------------ a real answer

def test_an_answered_office_reads_back(monkeypatch):
    _rows(monkeypatch, [_row("omar")])
    got = OC.for_office("omar")
    assert got.campaign == "RES-AT&T"
    assert got.bundle_type == "Base (Retail)"
    assert got.commission == ("Retail Comp Grid",)


def test_two_commission_bundles_split_on_the_pipe(monkeypatch):
    _rows(monkeypatch, [_row("omar", commission="One Grid | Two Grid")])
    assert OC.for_office("omar").commission == ("One Grid", "Two Grid")


def test_a_blank_bundle_is_allowed_because_the_page_reads_it(monkeypatch):
    """Under a bundle type the dropdown holds exactly one real option, and
    digi_docs refuses rather than guessing when it holds more. Asking an owner
    to retype a string the page can read is not an input this codebase takes."""
    _rows(monkeypatch, [_row("omar", bundle="")])
    assert OC.for_office("omar").bundle == ""
    assert OC.answered("omar") is True


def test_the_office_key_is_matched_case_insensitively(monkeypatch):
    _rows(monkeypatch, [_row("Omar")])
    assert OC.answered("OMAR") is True


def test_an_office_not_on_the_tab_says_it_was_never_asked(monkeypatch):
    _rows(monkeypatch, [_row("omar")])
    with pytest.raises(OC.NotAnswered, match="never been asked"):
        OC.for_office("cody")


def test_a_missing_tab_refuses_rather_than_defaulting(monkeypatch):
    """A sheet that cannot be read is unread, never 'this office has no
    special bundle' ([[feedback_empty_means_proven_zero]])."""
    monkeypatch.setattr(OC, "_rows", lambda book=None: [])
    assert OC.answered("omar") is False
