"""Tests for the stale in-progress-mark sweep.

What this locks down (Megan 2026-08-20): a CLOSED post must not keep telling the
channel that somebody is working it, an OPEN one must be left exactly as it is,
and the ✅ is never touched. Plus the one thing the sweep CAN'T do — remove a
mark somebody added by hand — has to be reported rather than silently skipped.

    python -m unittest automations.shared.test_incident_sweep -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automations.shared import incident_sweep as sweep
from automations.shared import incident_thread as inc

LUCY = inc.LUCY_USER_ID
HUMAN = "U0HUMAN0001"


class FakeClient:
    """Channel history with a reaction layer — the half FakeClient in
    test_incident_thread doesn't model, because nothing there reads it back."""

    def __init__(self, messages):
        self.messages = messages          # oldest first, as given
        self.removed = []                 # (ts, name)

    def auth_test(self):
        return {"user_id": LUCY}

    def conversations_history(self, *, channel, limit=200, cursor=None,
                              oldest=None, **_kw):
        return {"messages": list(reversed(self.messages))}   # newest first

    def reactions_remove(self, *, channel, timestamp, name):
        for m in self.messages:
            if m["ts"] != timestamp:
                continue
            for rx in m.get("reactions") or []:
                if rx["name"] != name:
                    continue
                if LUCY not in rx["users"]:
                    # Exactly what Slack answers for someone else's reaction.
                    raise RuntimeError("no_reaction")
                rx["users"].remove(LUCY)
        self.removed.append((timestamp, name))
        return {"ok": True}

    def chat_getPermalink(self, *, channel, message_ts):
        return {"permalink": "https://slack/{}".format(message_ts)}


def _post(ts, key, state, reactions=None, head="*r* — broke"):
    return {"ts": ts,
            "text": "{}\n\n{}".format(head, inc.marker(key, state)),
            "reactions": [{"name": n, "users": list(u)}
                          for n, u in (reactions or [])]}


class IncidentSweepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._real = sweep.REPORT_PATH
        sweep.REPORT_PATH = Path(self.tmp.name) / "stray.md"
        self.addCleanup(lambda: setattr(sweep, "REPORT_PATH", self._real))

    def _sweep(self, messages, *, apply=True):
        c = FakeClient(messages)
        return c, sweep.sweep(channel="C1", apply=apply, client=c)

    def test_lucys_mark_on_a_closed_post_comes_off(self):
        c, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("pending", [LUCY])])])
        self.assertEqual(out["cleared"], 1)
        self.assertIn(("1.0", "pending"), c.removed)

    def test_an_open_post_is_never_touched(self):
        """It might be somebody who really IS on it. The sweep only ever acts on
        a post whose own marker says the incident is closed."""
        c, out = self._sweep([_post("1.0", "failure-r", "open",
                                    [("pending", [LUCY])])])
        self.assertEqual(out["cleared"], 0)
        self.assertEqual(c.removed, [])

    def test_the_check_is_never_removed(self):
        """A resolved post is SUPPOSED to wear the ✅ — leaving it is the point."""
        c, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("white_check_mark", [LUCY]),
                                     ("pending", [LUCY])])])
        self.assertEqual([n for _, n in c.removed], ["pending"])

    def test_the_purple_waiting_mark_is_swept_too(self):
        c, _ = self._sweep([_post("1.0", "standalone-x", "resolved",
                                  [("large_purple_circle", [LUCY])])])
        self.assertIn(("1.0", "large_purple_circle"), c.removed)

    def test_a_hand_added_mark_is_reported_not_removed(self):
        """Slack only lets you remove your OWN reaction, so Lucy physically
        cannot clear these. Megan 2026-08-20 chose the quiet option: list them,
        no channel message."""
        c, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("pending", [HUMAN])],
                                    head="*Applicant Push* — didn't finish")])
        self.assertEqual(out["by_hand"], 1)
        self.assertEqual(out["cleared"], 0)
        self.assertEqual(c.removed, [], "we don't even try — Slack would refuse")
        written = sweep.REPORT_PATH.read_text(encoding="utf-8")
        self.assertIn("Applicant Push", written)
        self.assertIn("failure-r", written)

    def test_a_post_both_of_us_marked_loses_only_lucys_half(self):
        c, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("pending", [LUCY, HUMAN])])])
        self.assertEqual((out["cleared"], out["by_hand"]), (1, 1))
        self.assertIn(("1.0", "pending"), c.removed)

    def test_a_message_with_no_incident_marker_is_ignored(self):
        msg = {"ts": "1.0", "text": "just someone talking",
               "reactions": [{"name": "pending", "users": [LUCY]}]}
        c, out = self._sweep([msg])
        self.assertEqual((out["closed"], out["cleared"]), (0, 0))
        self.assertEqual(c.removed, [])

    def test_dry_run_changes_nothing(self):
        c, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("pending", [LUCY])])], apply=False)
        self.assertEqual(out["cleared"], 1, "it still says what it would do")
        self.assertEqual(c.removed, [], "…and does none of it")

    def test_a_clean_channel_writes_an_empty_list(self):
        _, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("white_check_mark", [LUCY])])])
        self.assertEqual(out["by_hand"], 0)
        self.assertIn("None.", sweep.REPORT_PATH.read_text(encoding="utf-8"))

    def test_a_slack_outage_sweeps_nothing_and_does_not_raise(self):
        """This runs inside the 4am batch. It may fail; it may not throw — and
        it must not report itself green either. A sweep that couldn't read the
        channel swept nothing, so it says so and main() exits non-zero
        [[project_report_verify_gap]]."""
        class Broken(FakeClient):
            def conversations_history(self, **_kw):
                raise RuntimeError("ratelimited")
        out = sweep.sweep(channel="C1", apply=True, client=Broken([]))
        self.assertEqual(out["cleared"], 0)
        self.assertFalse(out["ok"], "a failed read is not a clean run")

    def test_a_sweep_that_ran_says_so(self):
        _, out = self._sweep([_post("1.0", "failure-r", "resolved",
                                    [("pending", [LUCY])])])
        self.assertTrue(out["ok"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
