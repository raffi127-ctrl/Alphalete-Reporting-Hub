"""One channel whose dedup READ fails must not fail the whole tracker run.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_channel_read_failure

WHAT THIS GUARDS (2026-08-13). The ~7am Box catch-up posted 14 of 15 orgs and
still exited 1: #precisionmanagement-nds-sales (drew) blew up on
conversations.history — the "what's already posted today?" read that every post
starts with. That one channel's read error propagated out as a hard failure, so
the orchestrator retried the ENTIRE report 3× and the daily email called a run
that delivered 14 orgs a failure.

Three things have to stay true:
  1. A failed history/replies read degrades to a SOFT miss for that channel only
     (`soft: True`), and NOTHING is posted there — posting blind would create a
     second tracker thread in the channel (and one more per retry).
  2. The other channels/orgs in the same run still post normally.
  3. run.py's classification keeps a soft-only run at exit 0 (INCOMPLETE, alerted,
     re-runnable) instead of exit 1.
Plus: the logged error names the Slack CODE (`not_in_channel`), because the
original failure was undiagnosable — our own str(e)[:120] cut the message off at
`{'ok'...`, before the one word that says which fix is needed.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.tableau_screenshots import slack_post as sp
from automations.tableau_screenshots import pages as pg


class _Resp(dict):
    """Stand-in for slack_sdk's SlackResponse: dict access + status_code."""

    def __init__(self, error: str, status_code: int = 200, **extra):
        super().__init__(ok=False, error=error, **extra)
        self.status_code = status_code
        self.headers = {"Retry-After": "1"}
        self.data = dict(self)


class _ApiError(Exception):
    """Stand-in for slack_sdk.errors.SlackApiError (same .response contract)."""

    def __init__(self, response):
        self.response = response
        super().__init__(f"The request to the Slack API failed. {response}")


class _Client:
    """Minimal Slack stub. `history_errors[channel]` = the error code that
    channel's conversations.history raises; every other call succeeds."""

    def __init__(self, history_errors=None, ratelimit_once=()):
        self.history_errors = history_errors or {}
        self.ratelimit_once = set(ratelimit_once)
        self.posted = []          # (channel, kind)
        self.history_calls = 0

    def conversations_history(self, channel, **kw):
        self.history_calls += 1
        if channel in self.ratelimit_once:
            self.ratelimit_once.discard(channel)
            raise _ApiError(_Resp("ratelimited", 429))
        if channel in self.history_errors:
            raise _ApiError(_Resp(self.history_errors[channel]))
        return {"messages": []}          # no thread today → post a fresh one

    def conversations_replies(self, channel, ts, **kw):
        return {"messages": []}

    def chat_postMessage(self, channel, text, **kw):
        self.posted.append((channel, "parent"))
        return {"ok": True, "ts": "111.222"}

    def files_upload_v2(self, channel, **kw):
        self.posted.append((channel, "image"))
        return {"ok": True, "file": {"id": "F1"}}

    def reactions_add(self, **kw):
        return {"ok": True}

    def chat_update(self, **kw):
        return {"ok": True}


def _caps():
    return [(p, f"/x/{p['id']}.png") for p in pg.PAGES if not pg.is_late(p)]


class DedupReadFailureTest(unittest.TestCase):
    TODAY = dt.date(2026, 8, 13)
    DREW = "C0A7871FAUV"           # #precisionmanagement-nds-sales

    def _use(self, client):
        real = sp.smp._client
        sp.smp._client = lambda *a, **k: client
        self.addCleanup(setattr, sp.smp, "_client", real)
        # No 3s inter-upload sleep in tests — that pacing is a Slack ordering
        # concern, not behavior under test.
        real_sleep = sp.time.sleep
        sp.time.sleep = lambda *_a, **_k: None
        self.addCleanup(setattr, sp.time, "sleep", real_sleep)

    def _org_with(self, channel):
        """A throwaway org pointed at `channel` (registry restored after)."""
        orig_c, orig_l = dict(sp.ORG_CHANNELS), dict(sp.ORG_LABEL)
        sp.ORG_CHANNELS["_t"] = [channel]
        sp.ORG_LABEL["_t"] = f"#test-{channel}"
        self.addCleanup(lambda: (sp.ORG_CHANNELS.clear(),
                                 sp.ORG_CHANNELS.update(orig_c),
                                 sp.ORG_LABEL.clear(),
                                 sp.ORG_LABEL.update(orig_l)))
        return "_t"

    def test_history_failure_is_soft_and_posts_nothing(self):
        client = _Client(history_errors={self.DREW: "not_in_channel"})
        self._use(client)
        res = sp.post_all(_caps(), pg.PAGES, self.TODAY,
                          org=self._org_with(self.DREW))
        self.assertFalse(res["ok"])
        (ch,) = res["channels"]
        self.assertTrue(ch["soft"], "an unreadable channel must be a SOFT miss")
        self.assertIn("not_in_channel", ch["error"])
        self.assertEqual(client.posted, [],
                         "posted into a channel we couldn't read — that's the "
                         "duplicate-thread bug")

    def test_a_readable_channel_in_the_same_run_still_posts(self):
        client = _Client(history_errors={self.DREW: "not_in_channel"})
        self._use(client)
        good = sp.post_all(_caps(), pg.PAGES, self.TODAY,
                           org=self._org_with("C_GOOD"))
        self.assertTrue(good["ok"])
        self.assertIn(("C_GOOD", "parent"), client.posted)

    def test_soft_only_run_exits_zero(self):
        """run.py's classification: soft misses are INCOMPLETE, not exit 1."""
        client = _Client(history_errors={self.DREW: "not_in_channel"})
        self._use(client)
        posted_ok, posted_soft, posted_bad = [], [], []
        for org, ch in (("good", "C_GOOD"), ("drew", self.DREW)):
            res = sp.post_all(_caps(), pg.PAGES, self.TODAY,
                              org=self._org_with(ch))
            chans = res.get("channels", [])
            soft = [c for c in chans if not c.get("ok") and c.get("soft")]
            hard = [c for c in chans if not c.get("ok") and not c.get("soft")]
            if res.get("ok"):
                posted_ok.append(org)
            elif soft and not hard and not res.get("error"):
                posted_soft.append(org)
            else:
                posted_bad.append(org)
        self.assertEqual(posted_ok, ["good"])
        self.assertEqual(posted_soft, ["drew"])
        self.assertEqual(posted_bad, [])
        self.assertEqual(1 if posted_bad else 0, 0)     # the exit code

    def test_rate_limit_retries_once_then_succeeds(self):
        client = _Client(ratelimit_once=[self.DREW])
        self._use(client)
        res = sp.post_all(_caps(), pg.PAGES, self.TODAY,
                          org=self._org_with(self.DREW))
        self.assertTrue(res["ok"], "a single 429 should be waited out, not fatal")
        self.assertEqual(client.history_calls, 2)

    def test_error_text_names_the_slack_code(self):
        """The whole reason 8/13 was undiagnosable: the code never reached the log."""
        self.assertEqual(sp._slack_err(_ApiError(_Resp("not_in_channel"))),
                         "not_in_channel (HTTP 200)")
        self.assertIn("missing_scope",
                      sp._slack_err(_ApiError(_Resp("missing_scope", 200,
                                                    needed="channels:history"))))
        self.assertIn("ValueError", sp._slack_err(ValueError("boom")))


if __name__ == "__main__":
    unittest.main()
