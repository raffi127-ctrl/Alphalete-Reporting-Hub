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

import http.client

import pytest

from automations.new_start_followup import screenshot_roster as SR

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
