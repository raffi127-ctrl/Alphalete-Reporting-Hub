"""Slack reads survive a truncated body -- and writes are never wrapped.

    python -m pytest automations/shared/test_slack_retry.py

OFFLINE. Nothing here opens a socket or addresses Slack: the "API call" is a
closure that raises whatever the test wants it to.

The fault being reproduced is the real one from 2026-09-20: Slack closed the
connection with 74,664 of 178,739 promised bytes delivered, three times in
half an hour, and New-Start Thread Replies failed twice on it -- once as an
INCOMPLETE, once as a bare traceback.
"""
from __future__ import annotations

import http.client

import pytest

from automations.shared import slack_retry as R


def _truncated():
    """The exact shape Slack produced: partial body, more promised."""
    return http.client.IncompleteRead(b"x" * 74664, 104075)


class _Wrapped(Exception):
    """Stands in for requests' ChunkedEncodingError -- raised FROM the
    IncompleteRead, which is how requests actually delivers it."""


def _calls(*outcomes):
    """A fake API call that yields `outcomes` in order; an exception is raised,
    anything else returned. Records how many times it was called."""
    box = {"n": 0}

    def call(**kwargs):
        box["n"] += 1
        out = outcomes[min(box["n"] - 1, len(outcomes) - 1)]
        if isinstance(out, BaseException):
            raise out
        return out

    return call, box


# --- what counts as transient -----------------------------------------------
def test_a_truncated_body_is_transient():
    assert R.is_transient(_truncated())


def test_a_wrapped_truncation_is_found_through_the_chain():
    """requests raises ChunkedEncodingError FROM the IncompleteRead, so the
    name on the outside tells you nothing -- the chain has to be walked."""
    try:
        raise _Wrapped("connection broken") from _truncated()
    except _Wrapped as exc:
        assert R.is_transient(exc)


def test_slack_saying_no_is_not_transient():
    """A bad token or a missing scope is a real fault; retrying it only makes
    the failure slower and the log longer."""
    assert not R.is_transient(RuntimeError("invalid_auth"))
    assert not R.is_transient(ValueError("channel_not_found"))


def test_a_timeout_is_deliberately_not_retried():
    """The caller's own timeout already bounds it, and tripling a 60s wait for
    a case we have not seen costs more than it saves."""
    assert not R.is_transient(TimeoutError("read timed out"))


# --- the retry itself -------------------------------------------------------
def test_a_read_that_truncates_once_succeeds_on_the_retry():
    call, box = _calls(_truncated(), {"messages": ["ok"]})
    got = R.read(call, channel="C123", _sleeper=lambda s: None)
    assert got == {"messages": ["ok"]} and box["n"] == 2


def test_a_read_that_never_recovers_reraises_the_real_error():
    """Widen the attempts, never the number of failures swallowed."""
    call, box = _calls(_truncated())
    with pytest.raises(http.client.IncompleteRead):
        R.read(call, channel="C123", _sleeper=lambda s: None)
    assert box["n"] == 3                      # _TRIES, not forever


def test_a_real_fault_is_reraised_immediately():
    call, box = _calls(RuntimeError("invalid_auth"), {"messages": []})
    with pytest.raises(RuntimeError):
        R.read(call, channel="C123", _sleeper=lambda s: None)
    assert box["n"] == 1                      # no retry, no delay


def test_the_knobs_cannot_collide_with_slacks_own_parameters():
    """Underscore-prefixed on purpose: `limit`, `channel` and `ts` all go
    through **kwargs to the API call."""
    seen = {}

    def call(**kwargs):
        seen.update(kwargs)
        return {"messages": []}

    R.read(call, channel="C123", ts="1.2", limit=200, _sleeper=lambda s: None)
    assert seen == {"channel": "C123", "ts": "1.2", "limit": 200}


def test_it_backs_off_between_attempts():
    slept = []
    call, _ = _calls(_truncated(), _truncated(), {"messages": []})
    R.read(call, _sleeper=slept.append)
    assert slept == [1.0, 2.0]


def test_describe_names_the_truncation_in_bytes():
    assert R.describe(_truncated()) == (
        "Slack's response stopped early (74664 of 178739 bytes)")


# --- the rule that keeps this safe ------------------------------------------
def test_there_is_no_helper_for_writes():
    """A truncated chat_postMessage may well have POSTED before the body came
    apart, so retrying it is how one reply becomes two in front of the team.
    If a `write`/`post`/`call` helper ever appears here, that reasoning has to
    be revisited first -- this test is the reminder, not a style check."""
    public = {n for n in dir(R) if not n.startswith("_")}
    assert "read" in public
    assert not {"write", "post", "send", "call"} & public
