"""An EXPECTED miss must not be worded as a break.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_expected_miss_wording

WHAT THIS GUARDS (Megan 2026-09-05). daily_rep_breakdown ran 04:58-06:27 on
Lucy 3, posted, and filled every owner but Kim Rodriguez — who had moved states
and was waiting on a NEW OwnerVille account, so there was nothing to reach. The
report knew: its own manifest note said

    1 owner(s) still missing after retry sweep: expected, no action —
    terminated / pending access / no tab (Kim Rodriguez (name not found in
    ownerville — it lists: 'marcial rodriguez'))

and the channel nonetheless got, in the same thread:

    dropped 1 section this run — it did NOT post.
    The thread is live but incomplete.
    Needs one of you. It did not finish. Still not fixed after the noon
    cut-off. Re-running will not fix it.

Three wrong claims over one healthy run. Two separate causes:

  * `kind="owner"` did not exist in section_drop_alert's table, so it fell
    through to 'section', whose every word is about a Slack thread — while this
    report fills a per-owner TAB.
  * incident_triage had no signature for an expected miss, so the backstop
    branch reached its "It did not finish." default.

Both are the mistake _FINDING_PREFIXES was already added to fix: a triage line
that contradicts the post above it teaches people the line is noise.
"""
from __future__ import annotations

import unittest
import unittest.mock

from automations.shared import incident_triage as tri
from automations.shared import section_drop_alert as sda


EXPECTED_TAIL = ("1 owner(s) still missing after retry sweep: expected, no "
                 "action — terminated / pending access / no tab (Kim Rodriguez "
                 "(name not found in ownerville — it lists: 'marcial "
                 "rodriguez')).")


class TheDropAlertKinds(unittest.TestCase):
    def test_owner_kind_exists_and_is_not_about_a_thread(self):
        """It fell through to 'section' and talked about a thread that had in
        fact posted."""
        k = sda._KINDS["owner"]
        self.assertEqual(k["what"], "owner")
        blob = " ".join(str(v) for v in k.values()).lower()
        self.assertNotIn("did not post", blob)
        self.assertNotIn("thread is live but incomplete", blob)

    def test_expected_kind_says_the_run_was_fine(self):
        k = sda._KINDS["owner_expected"]
        self.assertIn("ran fine", k["headline"])
        self.assertTrue(k["headline"].startswith("✅"))
        blob = " ".join(str(v) for v in k.values()).lower()
        self.assertIn("nothing to re-run", blob)

    def test_the_expected_kind_is_never_the_loud_one(self):
        self.assertNotIn("🚨", sda._KINDS["owner_expected"]["headline"])
        self.assertIn("🚨", sda._KINDS["owner"]["headline"])


class TheTriageLine(unittest.TestCase):
    def _line(self, tail, hour):
        with unittest.mock.patch.object(tri, "_log_tail", return_value=tail):
            v = tri.classify("drop-daily-rep-breakdown", now_hour=hour)
        return v, tri.line_for(v)

    def test_an_expected_miss_is_not_did_not_finish(self):
        """The exact 2026-09-05 line, at the hour it was posted."""
        v, line = self._line(EXPECTED_TAIL, 12)
        self.assertNotIn("did not finish", line.lower())
        self.assertNotIn("noon cut-off", line.lower())
        self.assertIn("Nothing to do", line)

    def test_it_holds_before_the_backstop_too(self):
        _v, line = self._line(EXPECTED_TAIL, 8)
        self.assertIn("Nothing to do", line)

    def test_it_says_it_fixes_itself(self):
        _v, line = self._line(EXPECTED_TAIL, 12)
        self.assertIn("fills itself", line)

    def test_a_real_failure_is_still_loud(self):
        """The quiet path must never swallow a genuine break."""
        _v, line = self._line("Traceback: TimeoutError on owner tab", 13)
        self.assertNotIn("Nothing to do", line)

    def test_no_log_tail_is_unaffected(self):
        _v, line = self._line("", 13)
        self.assertNotIn("Nothing to do", line)


class TheReportPicksTheKind(unittest.TestCase):
    """daily.py chooses owner_expected only when EVERY remaining miss is in the
    do-not-retry bucket — one genuine failure alongside them keeps it loud."""

    @staticmethod
    def _kind(terminal_left, failed_after, deferred):
        return ("owner_expected"
                if (terminal_left and not failed_after and not deferred)
                else "owner")

    def test_all_expected(self):
        self.assertEqual(self._kind({"Kim Rodriguez": "name not found"}, [], []),
                         "owner_expected")

    def test_one_real_failure_alongside_keeps_it_loud(self):
        self.assertEqual(
            self._kind({"Kim Rodriguez": "name not found"}, ["Someone"], []),
            "owner")

    def test_deferred_keeps_it_loud(self):
        self.assertEqual(
            self._kind({"Kim Rodriguez": "name not found"}, [], ["Someone"]),
            "owner")

    def test_no_expected_at_all(self):
        self.assertEqual(self._kind({}, ["Someone"], []), "owner")

    def test_daily_py_really_contains_this_rule(self):
        """_kind above is a COPY of daily.py's expression, so on its own it
        would still pass if that line were deleted. Pin the real one."""
        import inspect
        from automations.focus_office_att import daily
        src = inspect.getsource(daily._daily_manifest_ok)
        self.assertIn('"owner_expected"', src)
        self.assertIn("not failed_after and not deferred", src)
        self.assertIn("kind=kind", src)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
