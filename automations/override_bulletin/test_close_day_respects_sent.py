"""--close-day must not announce "did not go out" about a week that went out.

Fri 2026-09-04: Eve was off, so the Override Bulletin for WE 8.30.26 was
released by hand through the send lever (`send.py --send`) instead of through
her checkmark. `close_day` reads the REACTION on the review post, so the 13:00
pass of deploy/override_bulletin_send_fri.sh was going to reply "Not sent —
nobody approved … Approve here and it still will" into the very thread whose
reply above it already said the full distro had it — an hour after the org got
the email.

The reaction is not the only proof a week went out. The confirmation reply is,
and it is ALREADY the once-a-week lock `already_sent` reads, so the closer
trusts it too. CLOSED_MARK and SENT_MARK both stand it down; only a thread
carrying neither, on a post nobody ticked, is a week that really ended unsent.
"""
import pytest

from automations.override_bulletin import override_gate as G
from automations.override_bulletin import review_gate as RG


class _Client:
    def __init__(self, replies):
        self._replies = replies
        self.posted = []

    def conversations_replies(self, **_k):
        # replies[0] is the parent — _said skips it, so mirror the real shape.
        return {"messages": [{"text": "the review post"}] + self._replies}

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ok": True}


@pytest.fixture
def gate(monkeypatch):
    def _setup(replies, reactions=()):
        client = _Client(replies)
        monkeypatch.setattr(RG, "_client", lambda: client)
        monkeypatch.setattr(RG, "_channel", lambda c=None: "C0BLLU9M0A2")
        monkeypatch.setattr(RG, "_mentions", lambda: "<@U088E2KJEV8>")
        monkeypatch.setattr(
            G, "_find_post",
            lambda *a, **k: {"ts": "1788531011.223409",
                             "reactions": list(reactions)})
        return client
    return _setup


def test_it_stands_down_when_the_thread_says_it_was_sent(gate):
    client = gate([{"text": f":white_check_mark: {G.SENT_MARK} Megan · WE 8.30.26"}])
    assert G.close_day("8.30.26") is False
    assert client.posted == [], "contradicted a send that already happened"


def test_it_still_stands_down_on_a_second_close(gate):
    client = gate([{"text": f"<@U088E2KJEV8> — {G.CLOSED_MARK}: …"}])
    assert G.close_day("8.30.26") is False
    assert client.posted == []


def test_a_genuinely_unsent_week_is_still_closed(gate):
    client = gate([{"text": "just a reminder nudge"}])
    assert G.close_day("8.30.26") is True
    assert len(client.posted) == 1
    assert G.CLOSED_MARK in client.posted[0]["text"]


def test_an_approved_week_is_left_to_the_send_path(gate):
    client = gate([], reactions=[{"name": "white_check_mark",
                                 "users": ["U088E2KJEV8"]}])
    assert G.close_day("8.30.26") is False
    assert client.posted == []
