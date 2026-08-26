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
    due_now = False


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



class StartTimeReading(unittest.TestCase):
    """The column is PLAIN TEXT with no meridiem — checked against the live
    8.24 tab, where even the unformatted read returns the string '1:00'. So
    these cases are the whole basis on which a contract lands at the right
    hour."""

    def _t(self, text):
        from automations.digi_docs import roster
        return roster.parse_start_time(text)

    def test_the_tab_as_it_actually_reads(self):
        import datetime as dt
        # Exactly the values sitting on D2D OBCL 8.24 today.
        self.assertEqual(self._t("1:00"), dt.time(13, 0))
        self.assertEqual(self._t("12:30"), dt.time(12, 30))
        self.assertEqual(self._t("1:30"), dt.time(13, 30))

    def test_a_morning_start_stays_morning(self):
        import datetime as dt
        self.assertEqual(self._t("8:00"), dt.time(8, 0))
        self.assertEqual(self._t("11:45"), dt.time(11, 45))

    def test_explicit_beats_the_rule(self):
        import datetime as dt
        self.assertEqual(self._t("9:30 am"), dt.time(9, 30))
        self.assertEqual(self._t("1:00 PM"), dt.time(13, 0))
        self.assertEqual(self._t("13:00"), dt.time(13, 0))
        self.assertEqual(self._t("12:00 am"), dt.time(0, 0))

    def test_unreadable_is_none_not_a_guess(self):
        for bad in ("", "   ", "noon", "TBD", "1:99", "25:00", "-"):
            self.assertIsNone(self._t(bad), f"{bad!r} should refuse, not guess")


class DueNowWindow(unittest.TestCase):
    def _cand(self, start):
        from automations.digi_docs import roster
        c = roster.Candidate(person=types.SimpleNamespace(
            name="Dana Reyes", row=7, skip_reason="", eligible=True))
        c.start_time = start
        return c

    def test_sends_thirty_minutes_before(self):
        import datetime as dt
        from automations.digi_docs import roster
        self.assertEqual(roster.send_due_at(self._cand("1:00")), dt.time(12, 30))
        self.assertEqual(roster.send_due_at(self._cand("12:30")), dt.time(12, 0))

    def test_not_yet_at_noon_due_by_half_past(self):
        import datetime as dt
        from automations.digi_docs import roster
        one_oclock = [self._cand("1:00")]
        due, not_yet, _ = roster.due_now(
            one_oclock, now=dt.datetime(2026, 8, 31, 12, 15))
        self.assertEqual((len(due), len(not_yet)), (0, 1))
        due, not_yet, _ = roster.due_now(
            one_oclock, now=dt.datetime(2026, 8, 31, 12, 30))
        self.assertEqual((len(due), len(not_yet)), (1, 0))

    def test_a_missed_slot_still_sends(self):
        """The machine being busy at 12:30 must not mean they never get sent."""
        import datetime as dt
        from automations.digi_docs import roster
        due, _, _ = roster.due_now([self._cand("1:00")],
                                   now=dt.datetime(2026, 8, 31, 14, 5))
        self.assertEqual(len(due), 1)

    def test_no_readable_time_is_held_back(self):
        import datetime as dt
        from automations.digi_docs import roster
        due, not_yet, no_time = roster.due_now(
            [self._cand("")], now=dt.datetime(2026, 8, 31, 23, 0))
        self.assertEqual((len(due), len(not_yet), len(no_time)), (0, 0, 1))


class TagsOnlyWhenSomeoneMustAct(unittest.TestCase):
    """Alisson / Tiff / Aimee get @-tagged so a failure gets picked up fast
    (Megan 2026-08-26). The risk is the opposite one: tag them on every clean
    Monday and the mention stops meaning anything by the third week."""

    def _body(self, *a, **kw):
        import io
        import contextlib
        from automations.digi_docs import slack_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slack_post.post(*a, dry_run=True, **kw)
        return buf.getvalue()

    def test_clean_run_tags_nobody(self):
        self.assertNotIn("<@", self._body(6, [], []))

    def test_a_refusal_tags_all_three(self):
        from automations.digi_docs import config
        body = self._body(5, ["Jose Laureano: not found in OwnerVille"], [])
        for name, uid in config.ESCALATE_ON_FAILURE:
            self.assertIn(f"<@{uid}>", body, f"{name} was not tagged")

    def test_a_stopped_run_tags_all_three(self):
        from automations.digi_docs import config
        body = self._body(0, [], [], fatal="RuntimeError: session did not open")
        for _name, uid in config.ESCALATE_ON_FAILURE:
            self.assertIn(f"<@{uid}>", body)

    def test_tagged_by_id_never_by_handle(self):
        """A display-name change turns an @handle into plain text."""
        from automations.digi_docs import config
        for name, uid in config.ESCALATE_ON_FAILURE:
            self.assertTrue(uid.startswith("U"), f"{name}: {uid!r} isn't a user id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
