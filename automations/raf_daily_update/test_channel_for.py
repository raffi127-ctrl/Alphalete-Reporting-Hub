"""Where an office's Daily Update goes, now that the office answers it.

Megan, 2026-11-22: "the channel they want their daily update posted in
should also be asked on their enrollment form."
"""
from __future__ import annotations

import pytest

from automations.eco_onboarding import settings as ES
from automations.icd_onboarding import office_steps as OS
from automations.raf_daily_update import offices as OFF


def _sheet(monkeypatch, rows):
    monkeypatch.setattr(OS, "_rows", lambda *a, **k: rows)


def _row(key, channel):
    return {OS.COL_OFFICE: key, ES.COL_DAILY_CHANNEL: channel}


def test_the_offices_own_answer_wins_over_ours(monkeypatch):
    """The table's value is our guess at their room; theirs is their room."""
    _sheet(monkeypatch, [_row("raf", "C0NEWROOM1")])
    assert OFF.channel_for(OFF.get("raf"), log=lambda *a: None) == "C0NEWROOM1"


def test_an_office_that_has_not_answered_keeps_the_table(monkeypatch):
    _sheet(monkeypatch, [_row("raf", "")])
    raf = OFF.get("raf")
    assert OFF.channel_for(raf, log=lambda *a: None) == raf.channel


def test_an_office_with_neither_has_no_channel(monkeypatch):
    """algemar, cyrus and vincent today: nothing in the table, nothing
    answered. The run refuses to --post rather than inventing a room."""
    _sheet(monkeypatch, [])
    assert OFF.channel_for(OFF.get("algemar"), log=lambda *a: None) == ""


def test_a_name_where_an_id_belongs_falls_back_and_says_so(monkeypatch):
    """A channel NAME is accepted by any text box and then fails hours later
    when Lucy tries to post. Here it must not become the channel."""
    _sheet(monkeypatch, [_row("raf", "#rafs-office-recruiting")])
    said = []
    raf = OFF.get("raf")
    assert OFF.channel_for(raf, log=said.append) == raf.channel
    assert "not a channel id" in " ".join(said)


def test_a_pasted_slack_link_is_still_their_answer(monkeypatch):
    _sheet(monkeypatch, [_row("raf", "https://app.slack.com/client/T1/C0NEWROOM1")])
    assert OFF.channel_for(OFF.get("raf"), log=lambda *a: None) == "C0NEWROOM1"


def test_an_unreadable_sheet_does_not_lose_the_daily_update(monkeypatch):
    """Losing an office's Daily Update over a sheet read would be worse than
    posting to a slightly stale room."""
    monkeypatch.setattr(OS, "_rows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    said = []
    raf = OFF.get("raf")
    assert OFF.channel_for(raf, log=said.append) == raf.channel
    assert "could not read" in " ".join(said)


def test_answering_the_form_does_not_turn_posting_on(monkeypatch):
    """WHERE IS NOT WHETHER. `posts_in_own_channel` is Megan's go, one office
    at a time, and an answer on an enrolment form is not it -- otherwise
    filling in a form is how an office starts posting to real people."""
    _sheet(monkeypatch, [_row("algemar", "C0NEWROOM1")])
    alg = OFF.get("algemar")
    assert OFF.channel_for(alg, log=lambda *a: None) == "C0NEWROOM1"
    assert alg.posts_in_own_channel is False


def test_the_form_asks_for_it_and_refuses_a_name():
    """The question exists, is not required, and a name is refused at save
    -- the browser box refuses one as it is typed, but `problems` is what
    the save goes through."""
    q = [q for q in ES.ALL if q.field == "daily_channel"]
    assert len(q) == 1 and q[0].column == ES.COL_DAILY_CHANNEL
    assert q[0].kind == "channel"
    assert q[0].required is False, "an office with no room yet can still save"
    assert any("not its ID" in p
               for p in ES.problems({"daily_channel": "#my-office"}))
    assert not any("daily" in p.lower()
                   for p in ES.problems({"daily_channel": "C0AUAS88FGW"}))
    assert not any("daily" in p.lower() for p in ES.problems({}))


def test_the_column_is_created_by_the_form_like_the_others():
    """It is read by the Daily Update, so it has to be a column the form
    makes -- the exact thing that went wrong with Blue Ink and Rate of Pay
    on 2026-11-19, read by code and never on the sheet."""
    assert ES.COL_DAILY_CHANNEL in ES.columns_needed()
    assert ES.COL_DAILY_CHANNEL in ES.missing_columns(["Office", "State"])
