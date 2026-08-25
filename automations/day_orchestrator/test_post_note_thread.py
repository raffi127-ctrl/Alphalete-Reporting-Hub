"""`post_note thread=<ts>` replies into a thread instead of opening a new item.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_post_note_thread

WHY (Megan 2026-08-25). #claudecorrections is one-thread-per-problem: Megan
triages it by scanning TOP-LEVEL items and their reactions, so every top-level
post is a claim that there is a new problem to look at. A follow-up on something
already in the channel — retracting an earlier note, saying an item is waiting
on an upstream feed — is not a new problem, and posting it at top level costs a
triage decision on a non-item. `post_note` could only post at top level, so
notes typed by hand had no way to behave like incident_thread's own alerts,
which always reply into the thread.

The failure mode worth guarding is the QUIET one: Slack does not reject a
thread_ts it doesn't recognise — it posts the message at top level instead. A
typo'd or truncated ts would therefore produce exactly the stray channel item
the option exists to prevent, and it would look like it worked. So the ts is
validated before the call, and a bad one fails the queued row loudly.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.day_orchestrator.mini_control import _action_post_note

CH = "C0BK5PRG259"
TS = "1787568657.523449"


class _Slack:
    """Records chat_postMessage / chat_update kwargs instead of sending."""

    def __init__(self):
        self.calls: list[dict] = []
        self.edits: list[dict] = []

    def chat_postMessage(self, **kw):
        self.calls.append(kw)
        return {"ok": True}

    def chat_update(self, **kw):
        self.edits.append(kw)
        return {"ok": True}

    def auth_test(self):
        return {"user": "lucy"}


class _Patch:
    """Swap slack_metrics_post._client for the recorder."""

    def __init__(self):
        self.slack = _Slack()

    def __enter__(self):
        self._p = mock.patch(
            "automations.shared.slack_metrics_post._client",
            return_value=self.slack)
        self._p.start()
        return self.slack

    def __exit__(self, *a):
        self._p.stop()
        return False


class RepliesIntoTheThread(unittest.TestCase):

    def test_thread_ts_is_passed_to_slack(self):
        with _Patch() as slack:
            ok, msg = _action_post_note(f"{CH} thread={TS} one tight line")
        self.assertTrue(ok, msg)
        self.assertEqual(slack.calls[0]["thread_ts"], TS)
        self.assertEqual(slack.calls[0]["text"], "one tight line")

    def test_the_thread_token_is_stripped_out_of_the_text(self):
        """The reader must never see the plumbing."""
        with _Patch() as slack:
            _action_post_note(f"{CH} thread={TS} correcting an earlier note")
        self.assertNotIn("thread=", slack.calls[0]["text"])

    def test_the_result_line_says_where_it_landed(self):
        """`lucy status` is how anyone checks this worked, so it has to name the
        thread — 'posted to C0BK…' alone can't be told from a top-level post."""
        with _Patch():
            ok, msg = _action_post_note(f"{CH} thread={TS} hello")
        self.assertTrue(ok)
        self.assertIn(TS, msg)


class StillPostsTopLevel(unittest.TestCase):
    """The existing behaviour is untouched when thread= is absent."""

    def test_no_thread_token_means_no_thread_ts(self):
        with _Patch() as slack:
            ok, _ = _action_post_note(f"{CH} a brand new problem")
        self.assertTrue(ok)
        self.assertNotIn("thread_ts", slack.calls[0])
        self.assertEqual(slack.calls[0]["text"], "a brand new problem")

    def test_escaped_newlines_still_expand(self):
        """The queue carries the whole note in one Sheet cell."""
        with _Patch() as slack:
            _action_post_note(f"{CH} line one\\nline two")
        self.assertEqual(slack.calls[0]["text"], "line one\nline two")

    def test_escaped_newlines_expand_in_a_thread_reply_too(self):
        with _Patch() as slack:
            _action_post_note(f"{CH} thread={TS} line one\\nline two")
        self.assertEqual(slack.calls[0]["text"], "line one\nline two")


class ABadTsNeverBecomesATopLevelPost(unittest.TestCase):
    """THE QUIET FAILURE. Slack answers a bogus thread_ts by posting at top
    level, so an unvalidated ts produces the exact stray item this option is
    meant to prevent — and reports success."""

    def test_a_malformed_ts_is_rejected_before_the_call(self):
        for bad in ("1787568657", "p1787568657523449", "1787568657.52344",
                    "abc.def", "1787568657.5234499", ""):
            with self.subTest(ts=bad):
                with _Patch() as slack:
                    ok, msg = _action_post_note(f"{CH} thread={bad} hello")
                self.assertFalse(ok, f"{bad!r} should be rejected")
                self.assertEqual(slack.calls, [], "nothing may be posted")

    def test_a_thread_reply_with_no_text_is_rejected(self):
        with _Patch() as slack:
            ok, msg = _action_post_note(f"{CH} thread={TS}")
        self.assertFalse(ok)
        self.assertEqual(slack.calls, [])

    def test_a_missing_channel_id_is_still_rejected(self):
        with _Patch() as slack:
            ok, _ = _action_post_note("not-a-channel hello")
        self.assertFalse(ok)
        self.assertEqual(slack.calls, [])


class TheQueuesQuotingNeverReachesTheChannel(unittest.TestCase):
    """`--enqueue` joins its argv with shlex.join, so a note passed as ONE quoted
    argument arrives as a single shlex token. post_note takes the rest of the
    line verbatim, so those quotes used to be posted into the channel with the
    note — which is exactly what happened to the 8/25 captainship correction.
    """

    def test_a_fully_quoted_note_is_unwrapped(self):
        with _Patch() as slack:
            _action_post_note(f"{CH} 'Correction to my note: not one issue.'")
        self.assertEqual(slack.calls[0]["text"],
                         "Correction to my note: not one issue.")

    def test_it_is_unwrapped_for_a_thread_reply_too(self):
        with _Patch() as slack:
            _action_post_note(f"{CH} thread={TS} 'one tight line'")
        self.assertEqual(slack.calls[0]["text"], "one tight line")

    def test_an_unquoted_note_is_left_exactly_as_typed(self):
        """Two-plus tokens means it was never wrapped — splitting it would shred
        the note into words."""
        with _Patch() as slack:
            _action_post_note(f"{CH} plain words with  spacing")
        self.assertEqual(slack.calls[0]["text"], "plain words with  spacing")

    def test_mrkdwn_inside_a_quoted_note_survives(self):
        """*bold*, backticks and mentions have to reach Slack intact."""
        note = "*Board* is stale — see `run.py` <@U0BCG8F9B5Z>"
        with _Patch() as slack:
            _action_post_note(f"{CH} '{note}'")
        self.assertEqual(slack.calls[0]["text"], note)

    def test_an_unbalanced_apostrophe_does_not_break_the_post(self):
        """shlex raises on this; the raw text must still go out rather than the
        note being lost."""
        with _Patch() as slack:
            ok, _ = _action_post_note(f"{CH} Raf's board is stale")
        self.assertTrue(ok)
        self.assertEqual(slack.calls[0]["text"], "Raf's board is stale")


class EditsInPlace(unittest.TestCase):
    """A note that needs fixing is better rewritten than followed by a
    correction the channel has to read twice."""

    def test_edit_calls_chat_update_and_posts_nothing_new(self):
        with _Patch() as slack:
            ok, msg = _action_post_note(f"{CH} edit={TS} 'the fixed line'")
        self.assertTrue(ok, msg)
        self.assertEqual(slack.calls, [])
        self.assertEqual(slack.edits[0]["ts"], TS)
        self.assertEqual(slack.edits[0]["text"], "the fixed line")

    def test_the_result_line_says_it_edited(self):
        with _Patch():
            _, msg = _action_post_note(f"{CH} edit={TS} hello")
        self.assertIn("edited", msg)

    def test_a_malformed_edit_ts_is_rejected(self):
        with _Patch() as slack:
            ok, _ = _action_post_note(f"{CH} edit=p1787568657523449 hello")
        self.assertFalse(ok)
        self.assertEqual(slack.edits, [])

    def test_thread_and_edit_together_are_rejected(self):
        """An edit already knows which thread its message is in; accepting both
        would silently ignore one of them."""
        with _Patch() as slack:
            ok, _ = _action_post_note(f"{CH} thread={TS} edit={TS} hello")
        self.assertFalse(ok)
        self.assertEqual(slack.calls, [])
        self.assertEqual(slack.edits, [])


if __name__ == "__main__":
    unittest.main()
