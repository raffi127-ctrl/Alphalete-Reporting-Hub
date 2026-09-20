"""The 2026-09-20 failure: Slack truncated the read and the report died.

    python -m pytest automations/new_start_followup/test_slack_truncation.py

WHAT HAPPENED. New-Start Thread Replies failed twice inside half an hour, both
times on a Slack response that stopped mid-body:

  08:01  INCOMPLETE — Couldn't read the Main funnel roster screenshot
         (IncompleteRead(74352 bytes read, 104389 more expected))
  08:32  http.client.IncompleteRead: IncompleteRead(74664 bytes read,
         104075 more expected)   ← a bare traceback, through slack_sdk

Two transports, one fault. The 08:32 half -- every slack_sdk Web API read --
is covered by the retry handler on the shared client, and its own tests live
in automations/shared/test_slack_truncated_read.py. THIS file covers the other
half: the roster screenshot is fetched with plain `requests`, which never goes
near slack_sdk and so gets none of that.

OFFLINE. No socket, no Slack, no vision call -- the truncation is injected.
"""
from __future__ import annotations

import datetime as dt
import http.client

import pytest

from automations.new_start_followup import screenshot_roster as SR
from automations.new_start_followup import thread as TH

PNG = b"\x89PNG\r\n\x1a\n" + b"rosterbytes" * 40


def _truncated():
    return http.client.IncompleteRead(b"x" * 74352, 104389)


class _Resp:
    def __init__(self, body):
        self.content = body
        self.headers = {"Content-Type": "image/png"}

    def raise_for_status(self):
        return None


# --- the roster screenshot download -----------------------------------------
def test_the_roster_download_survives_one_truncation(monkeypatch):
    """08:01's failure. Attempt 1 comes apart, attempt 2 brings the image."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _truncated()
        return _Resp(PNG)

    monkeypatch.setattr(SR.requests, "get", fake_get)
    monkeypatch.setattr(SR.slack_retry.time, "sleep", lambda s: None)

    path = SR._download({"url_private_download": "https://files.slack/x.png",
                         "mimetype": "image/png", "name": "roster.png"},
                        "xoxp-test")
    assert path.read_bytes() == PNG
    assert calls["n"] == 2
    path.unlink()


def test_the_content_read_is_inside_the_retried_attempt(monkeypatch):
    """A chunked body truncates when .content is READ, not when get() returns.
    A retry wrapped around get() alone would re-raise on the same
    half-downloaded response, so this pins where the boundary is."""
    calls = {"n": 0}

    class _LateResp:
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self):
            return None

        @property
        def content(self):
            if calls["n"] == 1:
                raise _truncated()
            return PNG

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return _LateResp()

    monkeypatch.setattr(SR.requests, "get", fake_get)
    monkeypatch.setattr(SR.slack_retry.time, "sleep", lambda s: None)

    path = SR._download({"url_private_download": "https://files.slack/x.png",
                         "mimetype": "image/png"}, "xoxp-test")
    assert path.read_bytes() == PNG and calls["n"] == 2
    path.unlink()


def test_a_sign_in_page_is_still_a_hard_error(monkeypatch):
    """The guard that catches a token without files:read must NOT have become
    a retry loop -- that is a real fault and it has to say so at once."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return _Resp(b"<html>sign in to slack</html>")

    monkeypatch.setattr(SR.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="files:read"):
        SR._download({"url_private_download": "https://files.slack/x.png"},
                     "xoxp-test")
    assert calls["n"] == 1


# --- the thread read --------------------------------------------------------
# This is the call that actually killed the 09:30 run on 2026-09-20 —
# thread.find_anchor's conversations.history — AFTER the first fix had been
# deployed. The retry had been left to slack_sdk's own handler on the shared
# client, and on that machine the handler was never reached (slack_sdk never
# logged its per-attempt "Failed to send a request to Slack API server").
# requirements.txt says `slack_sdk>=3.21`, unpinned, so which slack_sdk a Lucy
# has is not something a report can depend on. These two pin the retry into
# code we ship.
class _Client:
    """A Slack client whose reads truncate the first `fail_n` times."""
    def __init__(self, anchor_ts, fail_history=0, fail_replies=0):
        self.anchor_ts = anchor_ts
        self.fail_history = fail_history
        self.fail_replies = fail_replies
        self.history_calls = 0
        self.replies_calls = 0

    def _anchor(self):
        return {"ts": self.anchor_ts, "user": "UAISHA",
                "text": "New Starts Scheduled for Monday"}

    def conversations_history(self, channel=None, limit=None):
        self.history_calls += 1
        if self.history_calls <= self.fail_history:
            raise _truncated()
        return {"messages": [self._anchor()]}

    def conversations_replies(self, channel=None, ts=None, limit=None):
        self.replies_calls += 1
        if self.replies_calls <= self.fail_replies:
            raise _truncated()
        return {"messages": [self._anchor()]}


def _friday():
    today = dt.date.today()
    return today - dt.timedelta(days=(today.weekday() - 4) % 7)


def _anchor_ts(friday):
    return str(dt.datetime.combine(friday, dt.time(15, 0)).timestamp())


def test_find_anchors_history_survives_one_truncation(monkeypatch):
    """The exact 09:30 failure: thread.py:116, conversations.history."""
    monkeypatch.setattr(TH.slack_retry.time, "sleep", lambda s: None)
    friday = _friday()
    cli = _Client(_anchor_ts(friday), fail_history=1)
    out = TH.read_thread(friday=friday, client=cli)
    assert cli.history_calls == 2
    assert out["anchor_ts"] == cli.anchor_ts


def test_reading_the_replies_survives_one_truncation(monkeypatch):
    monkeypatch.setattr(TH.slack_retry.time, "sleep", lambda s: None)
    friday = _friday()
    cli = _Client(_anchor_ts(friday), fail_replies=1)
    out = TH.read_thread(friday=friday, client=cli)
    assert cli.replies_calls == 2
    assert out["anchor_ts"] == cli.anchor_ts


def test_a_thread_read_that_never_recovers_still_raises(monkeypatch):
    """Three truncations in a row is not a wobble any more, and the report has
    to fail rather than post against a thread it could not read."""
    monkeypatch.setattr(TH.slack_retry.time, "sleep", lambda s: None)
    friday = _friday()
    cli = _Client(_anchor_ts(friday), fail_history=99)
    with pytest.raises(http.client.IncompleteRead):
        TH.read_thread(friday=friday, client=cli)
    assert cli.history_calls == 3
