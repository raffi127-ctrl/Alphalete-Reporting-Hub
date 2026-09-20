"""A half-read Slack answer must not kill a report — and must never re-send a post.

The bug this pins: 2026-09-20 the Country Sales Board review link never reached
#revision-emails. The gate's conversations.history came back truncated
(http.client.IncompleteRead: 66316 bytes read, 115436 more expected) and the
run died with exit 1 — after the PDF was built, rendered and uploaded to Drive.
slack_sdk retries connectivity errors, but a truncated body is not one of them.

The other half matters just as much: the retry is for READS only. A truncated
body means Slack already had the request, so re-sending chat.postMessage would
post twice, and the checker takes the newest post — a checkmark on the older
one would silently never send.
"""
import unittest
from http.client import IncompleteRead
from urllib.error import URLError

from automations.shared import slack_metrics_post as smp


API = "https://slack.com/api/"


def _can_retry(method: str, error) -> bool:
    """Would any of the client's handlers re-send this call?"""
    req = type("Req", (), {"url": API + method, "method": "POST"})()
    return any(h._can_retry(state=None, request=req, response=None, error=error)
               for h in smp._retry_handlers())


class ReadsAreRetried(unittest.TestCase):
    def test_the_call_that_failed(self):
        self.assertTrue(_can_retry("conversations.history",
                                   IncompleteRead(b"", 115436)))

    def test_the_other_reads_the_gates_make(self):
        for m in ("conversations.replies", "conversations.list",
                  "conversations.members", "users.list", "users.info",
                  "users.lookupByEmail", "auth.test", "search.messages"):
            with self.subTest(m):
                self.assertTrue(_can_retry(m, IncompleteRead(b"", 10)))

    def test_a_query_string_doesnt_hide_the_method(self):
        self.assertTrue(_can_retry("conversations.history?channel=C0ABC12DE",
                                   IncompleteRead(b"", 10)))


class WritesAreNot(unittest.TestCase):
    """Re-sending these is how one day gets two review posts."""

    def test_posting(self):
        for m in ("chat.postMessage", "chat.delete", "chat.update",
                  "reactions.add", "files.upload", "files.completeUploadExternal"):
            with self.subTest(m):
                self.assertFalse(_can_retry(m, IncompleteRead(b"", 10)))

    def test_a_channel_id_in_the_query_cant_fake_a_read(self):
        """The method is the last path segment, never the whole url."""
        self.assertFalse(
            _can_retry("chat.postMessage?text=conversations.history",
                       IncompleteRead(b"", 10)))


class TheBuiltinsSurvive(unittest.TestCase):
    def test_slack_sdks_own_connectivity_retry_is_still_there(self):
        self.assertTrue(_can_retry("chat.postMessage", URLError("reset")))

    def test_an_ordinary_error_is_not_retried(self):
        self.assertFalse(_can_retry("conversations.history", ValueError("nope")))


if __name__ == "__main__":
    unittest.main()
