"""Connecting an ICD's own Blue Ink account — what it refuses to save."""
from __future__ import annotations

import json

import pytest

from automations.icd_alerts import blueink_setup as BS


class Cancelled(Exception):
    pass


class FakeAsk:
    """Stands in for the dialogs module."""
    Cancelled = Cancelled

    def __init__(self, *, key="", choice=None, cancel=False):
        self.key, self.choice, self.cancel = key, choice, cancel
        self.messages = []
        self.asked = []

    def password(self, prompt):
        self.asked.append(prompt)
        if self.cancel:
            raise Cancelled()
        return self.key

    def choose(self, prompt, options):
        self.asked.append(prompt)
        if self.cancel:
            raise Cancelled()
        return self.choice if self.choice in options else options[-1]

    def message(self, body, error=False):
        self.messages.append(body)


@pytest.fixture
def eco(tmp_path, monkeypatch):
    monkeypatch.setattr(BS, "ECO_DIR", tmp_path)
    monkeypatch.setattr(BS, "CREDS_PATH", tmp_path / "blueink-creds.json")
    # never reach a browser in a test
    monkeypatch.setattr(BS, "_templates", lambda key: [])
    return tmp_path


# ------------------------------------------- the key is proved before saving

def test_a_key_blue_ink_rejects_is_not_saved(eco, monkeypatch):
    """A bad key looks exactly like a good one until the first real run, which
    is a week later on somebody's first day."""
    monkeypatch.setattr(BS, "_works", lambda k: "Blue Ink did not accept that key.")
    ask = FakeAsk(key="bad-key")
    said = BS.run(ask=ask, log=lambda *a: None)
    assert said == "key not accepted"
    assert not BS.CREDS_PATH.exists()
    assert ask.messages and "Nothing was saved" in ask.messages[0]


def test_a_key_that_reads_the_account_is_saved(eco, monkeypatch):
    monkeypatch.setattr(BS, "_works", lambda k: None)
    monkeypatch.setattr(BS, "have_session", lambda: False, raising=False)
    ask = FakeAsk(key="good-key", choice="Not now")
    BS.run(ask=ask, log=lambda *a: None)
    body = json.loads(BS.CREDS_PATH.read_text())
    assert body["blueink_api_key"] == "good-key"


def test_the_key_file_is_owner_only(eco, monkeypatch):
    monkeypatch.setattr(BS, "_works", lambda k: None)
    ask = FakeAsk(key="good-key", choice="Not now")
    BS.run(ask=ask, log=lambda *a: None)
    assert oct(BS.CREDS_PATH.stat().st_mode)[-3:] == "600"


def test_an_unreachable_blue_ink_is_not_called_a_bad_key(eco, monkeypatch):
    """"We could not reach Blue Ink" and "your key is wrong" send a person to
    two different places."""
    monkeypatch.setattr(
        BS, "_works", lambda k: "Blue Ink could not be reached (TimeoutError).")
    ask = FakeAsk(key="good-key")
    BS.run(ask=ask, log=lambda *a: None)
    assert "could not be reached" in ask.messages[0]


def test_an_empty_paste_is_left_for_later(eco):
    ask = FakeAsk(key="   ")
    assert BS.run(ask=ask, log=lambda *a: None) == "left for later"
    assert not BS.CREDS_PATH.exists()


def test_cancelling_saves_nothing(eco):
    ask = FakeAsk(cancel=True)
    assert BS.run(ask=ask, log=lambda *a: None) == "left for later"
    assert not BS.CREDS_PATH.exists()


# ------------------------------------------------------- where it is written

def test_it_is_written_under_the_home_not_the_repo():
    """The repo copy is replaced on every update, so a key parked inside it is
    destroyed by a git pull."""
    assert ".config" in str(BS.CREDS_PATH)
    assert "lucy-reports" in str(BS.CREDS_PATH)
    repo = str(__import__("pathlib").Path(__file__).resolve().parents[2])
    assert not str(BS.CREDS_PATH).startswith(repo)


def test_an_office_already_holding_a_key_is_not_asked_again(eco, monkeypatch):
    BS.CREDS_PATH.write_text(json.dumps({"blueink_api_key": "already"}))
    monkeypatch.setattr(BS, "have_key", lambda: True)
    ask = FakeAsk(choice="Not now")
    said = BS.run(ask=ask, log=lambda *a: None)
    assert "key already here" in said
    assert not any("API" in p for p in ask.asked)
