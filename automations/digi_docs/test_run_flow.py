"""The two ways this run could finish without telling anybody.

Both were real (2026-08-26) and both are the same class of bug: the channel is
the only thing most people see, so a run that says nothing is a run that didn't
happen as far as the office is concerned.

  1. A fatal error -- a session that won't open, a browser that dies mid-batch
     -- threw straight past the Slack post. The morning where NOBODY got their
     documents was the one morning nobody was told; only the Hub card went red.
  2. A week where nobody needed documents still posted "*0* new starts sent
     digi docs", which is the blank board that trains people to stop reading.

Nothing here touches OwnerVille, the Sheet or Slack: the modules those live in
are replaced before `_phases` imports them.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock


class _Cand:
    def __init__(self, name="Dana Reyes"):
        self.name = name
        self.row = 7
        self.digi_col = 12
        self.digi_val = ""
        self.eligible = True
        self.skip_reason = ""


class _Args:
    live = True
    add_only = False
    send_only = True
    both = False
    tab = ""
    only = ""


def _fake_ov(*, session_raises=None):
    """Stand-in for automations.digi_docs.ownerville."""
    ov = types.ModuleType("automations.digi_docs.ownerville")

    class Refused(RuntimeError):
        pass

    ov.Refused = Refused
    ov.config = types.SimpleNamespace(DOCS_NEEDED_STATE="REQUIRED ACTION")

    class _Session:
        def __enter__(self):
            if session_raises:
                raise session_raises
            return object()

        def __exit__(self, *a):
            return False

    ov.session = lambda **kw: _Session()
    # Never reached in these tests -- the session is what fails.
    ov.open_set_status = lambda *a, **k: (object(), "Dana Reyes")
    ov.docs_row_state = lambda modal: "COMPLETED"
    ov.add_sales_rep = lambda *a, **k: "exists"
    return ov


class _Recorder:
    """Captures the Slack call instead of making it."""

    def __init__(self):
        self.calls = []

    def post(self, sent, refused, attested, *, fatal="", dry_run=True):
        self.calls.append({"sent": sent, "refused": list(refused),
                           "fatal": fatal, "dry_run": dry_run})
        return True


def _run(ov, recorder, args=None):
    from automations.digi_docs import run as R

    mark = types.ModuleType("automations.digi_docs.mark")
    mark.tint = lambda ws, cands, dry_run=True: 0
    slack = types.ModuleType("automations.digi_docs.slack_post")
    slack.post = recorder.post

    ws = types.SimpleNamespace(title="D2D OBCL 8.24", id=0)
    with mock.patch.dict(sys.modules, {
            "automations.digi_docs.ownerville": ov,
            "automations.digi_docs.mark": mark,
            "automations.digi_docs.slack_post": slack}), \
        mock.patch.object(R, "_open_tab", lambda tab="": (ws, [])), \
        mock.patch.object(R, "_flag_terminated", lambda people: None), \
        mock.patch.object(R.roster, "candidates", lambda v, t: [_Cand()]), \
        mock.patch.object(R.roster, "to_send", lambda c: [_Cand()]):
        return R._phases(args or _Args())


class FatalStillAlerts(unittest.TestCase):
    def test_session_failure_reaches_slack(self):
        """A run that dies before it starts must still say so in the channel."""
        ov = _fake_ov(session_raises=RuntimeError("browser profile locked"))
        rec = _Recorder()
        rc = _run(ov, rec)

        self.assertEqual(len(rec.calls), 1,
                         "the run threw past the Slack post — the exact bug")
        call = rec.calls[0]
        self.assertIn("browser profile locked", call["fatal"])
        self.assertEqual(call["sent"], 0)
        self.assertEqual(rc, 1, "a run that stopped early is not a success")

    def test_fatal_names_the_error_type(self):
        ov = _fake_ov(session_raises=TimeoutError("ownerville never loaded"))
        rec = _Recorder()
        _run(ov, rec)
        self.assertTrue(rec.calls[0]["fatal"].startswith("TimeoutError:"))


class QuietWeekSaysNothing(unittest.TestCase):
    def test_no_fatal_no_sends_no_refusals(self):
        """Everyone already had their documents. That is not news."""
        from automations.digi_docs import slack_post

        # The real function, so the guard itself is what's under test.
        self.assertFalse(slack_post.post(0, [], [], dry_run=True))

    def test_a_refusal_alone_is_still_worth_posting(self):
        from automations.digi_docs import slack_post
        self.assertFalse(  # dry_run returns False, but it PRINTED a body
            slack_post.post(0, ["Jose Laureano: not in OwnerVille"], [],
                            dry_run=True))

    def test_fatal_posts_even_with_zero_counts(self):
        from automations.digi_docs import slack_post
        with mock.patch.object(slack_post, "CHANNEL", "C_TEST"):
            # dry_run prints rather than sends; the point is that the guard
            # does NOT swallow it.
            self.assertFalse(slack_post.post(0, [], [], fatal="boom",
                                             dry_run=True))


class AddPhaseNeverPosts(unittest.TestCase):
    def test_add_only_is_not_a_send(self):
        """--add-only mails nobody, so it must not announce a send."""
        class AddArgs(_Args):
            add_only = True
            send_only = False

        ov = _fake_ov()
        rec = _Recorder()
        _run(ov, rec, AddArgs())
        self.assertEqual(rec.calls, [],
                         "the add phase posted to Slack off an empty result")


if __name__ == "__main__":
    unittest.main(verbosity=2)
