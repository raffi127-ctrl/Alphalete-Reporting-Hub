"""Where an office's posts go, now that the office answers it.

Megan, 2026-11-22: the OBCL update's channel "will need to be asked on the
enrollment form", "they also need an option here to send to a text group",
and on Blue Ink -- "every ICD will have their own blueink account login.
that isn't something we have to build. we just have to make sure they have
their document bundle labeled correctly so lucy knows which to send out."
"""
from __future__ import annotations

import pytest

from automations.blueink_docs import config as BC
from automations.eco_onboarding import settings as ES
from automations.icd_onboarding import office_steps as OS
from automations.obcl_ov_sweep import snapshot as SN


def _sheet(monkeypatch, **cols):
    row = {OS.COL_OFFICE: "raf"}
    row.update(cols)
    monkeypatch.setattr(OS, "_rows", lambda *a, **k: [row])


# ------------------------------------------------------- the OBCL update

def test_slack_is_their_channel(monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL: "C0AUAS88FGW"})
    assert SN.destination("raf") == ("slack", "C0AUAS88FGW")


def test_a_text_group_is_their_group(monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_TEXT,
                           ES.COL_OBCL_GROUP: "EL PASO CREW"})
    assert SN.destination("raf") == ("text", "EL PASO CREW")


def test_not_yet_sends_nowhere_rather_than_somewhere_else(monkeypatch):
    """A fallback to the hardcoded group would put one office's board in
    another office's iMessage. Nothing sent is the safe answer."""
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_NEITHER})
    assert SN.destination("raf") == ("", "")


def test_a_destination_with_nothing_behind_it_sends_nowhere(monkeypatch):
    """Chose Slack, left the channel blank. The form refuses this, but a row
    edited by hand can still look like it."""
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL: ""})
    assert SN.destination("raf") == ("", "")


def test_a_pasted_slack_link_still_resolves(monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL:
                               "https://app.slack.com/client/T1/C0AUAS88FGW"})
    assert SN.destination("raf") == ("slack", "C0AUAS88FGW")


def test_an_unreadable_sheet_sends_nowhere(monkeypatch):
    monkeypatch.setattr(OS, "_rows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    assert SN.destination("raf") == ("", "")


def test_no_office_key_is_alphaletes_own_group():
    """Every caller that has not been taught about offices behaves exactly
    as it did -- Alphalete answered this by being the office the group was
    made for."""
    assert SN.destination("") == ("text", SN.GROUP)


def test_the_form_refuses_a_destination_with_nowhere_to_go():
    """"Chose Slack, no channel" reads as configured and sends nothing,
    which is worse than "not yet" because nobody goes looking for it."""
    assert any("Slack channel" in p
               for p in ES.problems({"obcl_to": ES.OBCL_SLACK}))
    assert any("text group" in p
               for p in ES.problems({"obcl_to": ES.OBCL_TEXT}))
    assert not any("OBCL" in p or "text group" in p
                   for p in ES.problems({"obcl_to": ES.OBCL_NEITHER}))


# -------------------------------------------------- the Blue Ink bundle

def test_the_bundle_name_is_the_offices_own(monkeypatch):
    _sheet(monkeypatch, **{ES.COL_BUNDLE: "SE7EN SUMMIT I9"})
    assert BC.template_name_for("raf") == "SE7EN SUMMIT I9"


def test_an_office_that_has_not_mapped_its_bundle_gets_nothing(monkeypatch):
    """Megan, 2026-11-22: "no one will be like alphalete's", "every ICD is
    going to be different". Handing back ours would send their own run
    hunting their account for a template that cannot be in it, and the
    failure would arrive one person at a time, mid-batch, looking like a
    Blue Ink fault."""
    _sheet(monkeypatch, **{ES.COL_BUNDLE: ""})
    assert BC.template_name_for("raf") == ""


def test_an_unreadable_sheet_is_not_a_reason_to_use_ours(monkeypatch):
    monkeypatch.setattr(OS, "_rows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    assert BC.template_name_for("raf") == ""


def test_no_office_key_is_alphalete_itself():
    """Every caller that has not been taught about offices behaves as it
    did -- the constant is Alphalete's own bundle and nobody else's."""
    assert BC.template_name_for("") == BC.TEMPLATE_NAME


def test_the_form_does_not_fill_a_bundle_name_in_for_them():
    """A real name in the box reads as answered and exists in no other
    account, so the first send of a new office's first week goes nowhere.
    A blank box is a question somebody answers."""
    q = [q for q in ES.ALL if q.field == "bundle"][0]
    assert q.default == ""
    assert "Templates" in q.help, "say where to go and look"


def test_an_office_with_blue_ink_must_map_its_bundle():
    assert any("bundle" in p for p in ES.problems({"blue_ink": "Yes"}))
    assert not any("bundle" in p for p in ES.problems({"blue_ink": "No"})), (
        "an office that skips Blue Ink is not asked to name a bundle")


def test_every_new_answer_is_a_column_the_form_creates():
    """Read by code and absent from the sheet is how Blue Ink and Rate of
    Pay broke on 2026-11-19."""
    need = ES.columns_needed()
    for col in (ES.COL_BUNDLE, ES.COL_OBCL_TO, ES.COL_OBCL_CHANNEL,
                ES.COL_OBCL_GROUP):
        assert col in need, col


# ------------------------- the setting we cannot set from here

def test_the_calendar_view_is_confirmed_on_the_form():
    """Raf's ask: the office's ApplicantStream calendar must be List view
    with Show Notes ticked. It is a setting on their own screen, so the
    only way a new office starts right is to be asked while setting up
    (Megan, 2026-11-22: "the enrollment is also where we would add this")."""
    q = [q for q in ES.ALL if q.field == "calendar_view"]
    assert len(q) == 1 and q[0].required
    assert q[0].choices == ("Yes", "Not yet")
    assert "Show Notes" in q[0].help and "List" in q[0].help


def test_not_yet_is_refused_rather_than_recorded():
    """Ten seconds on their own screen, and left wrong the training
    calendar reads short -- new starts do not appear at all, which looks
    like a quiet week rather than a fault."""
    said = ES.problems({"calendar_view": "Not yet"})
    assert any("List view" in p for p in said)
    assert not any("List view" in p
                   for p in ES.problems({"calendar_view": "Yes"}))


def test_it_is_a_column_the_form_creates():
    assert ES.COL_CALENDAR_VIEW in ES.columns_needed()
