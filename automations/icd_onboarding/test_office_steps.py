"""An office without Blue Ink — what it skips, and what it must not skip."""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import board as B
from automations.icd_onboarding import office_steps as OS

SUNDAY = dt.date(2026, 11, 8)


def _rows(monkeypatch, rows):
    monkeypatch.setattr(OS, "_rows", lambda book=None: rows)


def _row(office, blueink=""):
    return {"Office": office, "Owner": "X", OS.COL_BLUEINK: blueink}


# ------------------------------------------------- unknown is not the same as no

def test_an_office_nobody_asked_skips_nothing(monkeypatch):
    """Marking an unasked office n/a would quietly switch off a step that
    works. The columns stay open and the usual sources fill them."""
    _rows(monkeypatch, [_row("omar", "")])
    assert OS.uses_blueink("omar") is None
    assert OS.skipped_for("omar") == ()


def test_an_office_not_on_the_tab_at_all_skips_nothing(monkeypatch):
    _rows(monkeypatch, [])
    assert OS.uses_blueink("cody") is None
    assert OS.skipped_for("cody") == ()


def test_a_sheet_that_cannot_be_read_skips_nothing(monkeypatch):
    """Unread is never 'this office has no Blue Ink'."""
    monkeypatch.setattr(OS, "_rows", lambda book=None: [])
    assert OS.skipped_for("omar") == ()


# ------------------------------------------------------------- a real answer

def test_no_means_blue_ink_and_apex_are_skipped(monkeypatch):
    """Apex reads date of birth and address OUT OF the signed packet, so an
    office without an account can never do it."""
    _rows(monkeypatch, [_row("omar", "no")])
    assert OS.uses_blueink("omar") is False
    assert set(OS.skipped_for("omar")) == {"Blue Ink", "Added to APEX"}


def test_yes_skips_nothing(monkeypatch):
    _rows(monkeypatch, [_row("omar", "yes")])
    assert OS.uses_blueink("omar") is True
    assert OS.skipped_for("omar") == ()


def test_the_answer_is_read_loosely(monkeypatch):
    for said in ("Yes", "TRUE", "y", " on "):
        _rows(monkeypatch, [_row("omar", said)])
        assert OS.uses_blueink("omar") is True, said
    for said in ("No", "FALSE", "n", " none "):
        _rows(monkeypatch, [_row("omar", said)])
        assert OS.uses_blueink("omar") is False, said


def test_a_word_nobody_expected_is_unknown_not_no(monkeypatch):
    """"maybe" is not an answer, and treating it as no switches off two real
    steps."""
    _rows(monkeypatch, [_row("omar", "maybe?")])
    assert OS.uses_blueink("omar") is None


# ------------------------------------------- what the skipped columns say

def test_only_the_two_steps_that_depend_on_a_packet_are_skipped():
    """Nothing else on the board comes from Blue Ink, so nothing else goes."""
    assert set(OS.WITHOUT_BLUEINK) <= set(B.STEPS)
    assert set(OS.WITHOUT_BLUEINK) == {"Blue Ink", "Added to APEX"}


def test_the_marker_is_not_a_date_so_it_prints_as_itself():
    """board.cell_text turns a date into a tick; this has to read `n/a` on the
    leader's printed sheet instead."""
    assert B.cell_text(OS.NOT_APPLICABLE) == OS.NOT_APPLICABLE
    assert B.cell_text("11/09/2026") == "✓"


def test_a_marked_step_stops_counting_as_outstanding():
    """Otherwise the office reads as permanently behind and the printed sheet
    counts boxes nobody can ever tick."""
    row = {c: "" for c in B.STEPS}
    row.update({"Name": "Ada", "Last Name": "F"})
    assert set(OS.WITHOUT_BLUEINK) <= set(B.remaining(row))
    for c in OS.WITHOUT_BLUEINK:
        row[c] = OS.NOT_APPLICABLE
    assert not (set(OS.WITHOUT_BLUEINK) & set(B.remaining(row)))


def test_alphalete_is_known_without_asking_the_sheet(monkeypatch):
    _rows(monkeypatch, [])
    assert OS.uses_blueink("raf") is True


# ------------------------------------------------- Rate of Pay is per office

def test_an_office_nobody_asked_has_no_rate(monkeypatch):
    """Megan, 2026-11-12: Rate of Pay is asked at enrollment. $10.00 is
    ALPHALETE'S number -- handing it to another office puts a wrong rate on a
    real payroll record, and nobody would see it was wrong."""
    from automations.icd_onboarding import office_steps as OS
    monkeypatch.setattr(OS, "_rows", lambda book=None: [
        {"Office": "someone", "Blue Ink": "Yes"}])
    assert OS.rate_of_pay("someone") is None


def test_a_rate_is_read_and_normalised(monkeypatch):
    from automations.icd_onboarding import office_steps as OS
    monkeypatch.setattr(OS, "_rows", lambda book=None: [
        {"Office": "jacob", "Rate of Pay": "$12"},
        {"Office": "luke", "Rate of Pay": "11.5"}])
    assert OS.rate_of_pay("jacob") == "12.00"
    assert OS.rate_of_pay("luke") == "11.50"


def test_words_in_the_money_column_are_not_typed_in(monkeypatch):
    """A column somebody wrote 'commission' into is not a rate. Saying nothing
    holds the person back; typing it would reach the box Apex pays from."""
    from automations.icd_onboarding import office_steps as OS
    monkeypatch.setattr(OS, "_rows", lambda book=None: [
        {"Office": "jacob", "Rate of Pay": "commission only"}])
    assert OS.rate_of_pay("jacob") is None


def test_an_unreadable_sheet_is_not_a_rate(monkeypatch):
    from automations.icd_onboarding import office_steps as OS
    monkeypatch.setattr(OS, "_rows", lambda book=None: [])
    assert OS.rate_of_pay("jacob") is None
