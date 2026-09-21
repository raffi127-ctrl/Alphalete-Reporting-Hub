"""A Slack connection that never opened is retried — posts included — and
nothing else about the write rule loosens.

The bug this pins: 2026-09-21 cody_metrics posted 7/9. Rep Activations
(files.completeUploadExternal) and Sales 6+ Days Out (conversations.history)
both died on "_ssl.c:1112: The handshake operation timed out". slack_sdk
retries a URLError once, 30s per try, so a ~1-minute blip outlasted it.

A failed handshake means no request byte went out, so even a post is safe to
send again. A timeout mid-send or mid-read is NOT — Slack may have it.
"""
import socket
import ssl
import unittest
from http.client import IncompleteRead
from urllib.error import URLError

from automations.shared import slack_metrics_post as smp


API = "https://slack.com/api/"


def _handlers_that_retry(method: str, error):
    req = type("Req", (), {"url": API + method, "method": "POST"})()
    return [h for h in smp._retry_handlers()
            if h._can_retry(state=None, request=req, response=None, error=error)]


def _never_connected_retries(method, error) -> bool:
    return any(h.max_retry_count >= 4 for h in _handlers_that_retry(method, error))


HANDSHAKE = URLError(socket.timeout("_ssl.c:1112: The handshake operation timed out"))


class HandshakeTimeoutsGetMoreTries(unittest.TestCase):
    def test_the_two_calls_that_failed(self):
        for m in ("files.completeUploadExternal", "conversations.history"):
            with self.subTest(m):
                self.assertTrue(_never_connected_retries(m, HANDSHAKE))

    def test_posts_too_because_nothing_was_sent(self):
        self.assertTrue(_never_connected_retries("chat.postMessage", HANDSHAKE))

    def test_ssl_error_during_handshake(self):
        e = URLError(ssl.SSLError("handshake operation timed out"))
        self.assertTrue(_never_connected_retries("chat.postMessage", e))

    def test_refused_and_dns(self):
        for e in (URLError(ConnectionRefusedError(61, "refused")),
                  URLError(socket.gaierror(8, "nodename nor servname"))):
            with self.subTest(e):
                self.assertTrue(_never_connected_retries("chat.postMessage", e))


class MidRequestFailuresDoNot(unittest.TestCase):
    """Slack may already have these — the extra tries must not cover them."""

    def test_read_timeout_on_a_post(self):
        e = URLError(socket.timeout("The read operation timed out"))
        self.assertFalse(_never_connected_retries("chat.postMessage", e))

    def test_write_timeout_on_a_post(self):
        e = URLError(socket.timeout("The write operation timed out"))
        self.assertFalse(_never_connected_retries("chat.postMessage", e))

    def test_truncated_body_on_a_post(self):
        self.assertEqual(
            _handlers_that_retry("chat.postMessage", IncompleteRead(b"", 10)), [])

    def test_ordinary_error(self):
        self.assertEqual(
            _handlers_that_retry("chat.postMessage", ValueError("nope")), [])


if __name__ == "__main__":
    unittest.main()
