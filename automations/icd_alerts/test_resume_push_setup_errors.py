"""The setup screen's "Resume pushing" line says WHY, and tells us.

Drew, 2026-10-06: "Resume pushing  failed (Error)" and nothing else. "Error"
is patchright's base class, the real reason was in its message, and nothing
was sent to #claudecorrections-and-requests.

Every step and the relay are patched: nothing here opens Chrome, prompts, or
posts anywhere.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import finish_setup as F
from automations.icd_alerts import resume_push as RP


class Error(Exception):
    """Stands in for patchright's base exception -- same bare name."""


CLOSED = Error("Page.wait_for_timeout: Target page, context or browser has "
               "been closed")
NO_CDP = Error("BrowserType.connect_over_cdp: connect ECONNREFUSED "
               "127.0.0.1:9247\nCall log:\n  - <ws preparing>")


class _Setup(unittest.TestCase):
    """_resume_push with an office that wants pushing and a saved login."""

    def setUp(self):
        self.lines = []
        self.reports = []
        rows = [{"office_key": "drew", "push_resumes": True}]
        ps = [mock.patch.object(F.C, "enrollments", return_value=rows),
              mock.patch.object(F.C, "appstream_creds",
                                return_value={"username": "u", "password": "p"}),
              mock.patch.object(RP, "push_record",
                                return_value={"office_key": "drew"}),
              mock.patch("automations.icd_alerts.relay.report_fault",
                         side_effect=self._report)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def _report(self, stage, summary, detail="", **kw):
        self.reports.append({"stage": stage, "summary": summary,
                             "detail": detail, **kw})
        return True

    def step(self, **patches):
        with mock.patch.multiple(RP, **patches):
            return F._resume_push(self.lines.append)

    def said(self):
        return "\n".join(self.lines)


class TheRealReasonIsShown(_Setup):

    def test_a_closed_window_says_so_not_error(self):
        got = self.step(check_login=mock.Mock(side_effect=CLOSED))
        self.assertTrue(got.startswith("failed — "), got)
        self.assertNotEqual(got, "failed (Error)")
        self.assertIn("window was closed", got)
        self.assertIn("leave the Chrome window", self.said())
        # The library's own words are on screen too, for whoever reads it.
        self.assertIn("has been closed", self.said())

    def test_chrome_that_cannot_be_driven_names_the_port(self):
        got = self.step(check_login=mock.Mock(side_effect=NO_CDP))
        self.assertIn("could not take control of Lucy's Chrome", got)
        self.assertIn("9247", got)

    def test_an_unknown_error_keeps_its_whole_message(self):
        boom = ValueError("profile folder is read-only: /Users/x/lucy\nline 2")
        got = self.step(check_login=mock.Mock(side_effect=boom))
        self.assertIn("ValueError: profile folder is read-only", got)
        self.assertIn("line 2", self.said())

    def test_a_crash_adding_resume_helper_names_that_step(self):
        got = self.step(check_login=mock.Mock(return_value=0),
                        extension_installed=mock.Mock(return_value=False),
                        setup_extension=mock.Mock(side_effect=CLOSED))
        self.assertIn("window was closed", got)
        self.assertIn("adding Resume Helper", self.said())
        self.assertIn("adding Resume Helper", self.reports[0]["summary"])

    def test_chrome_that_never_opens_is_not_called_a_bad_login(self):
        got = self.step(check_login=mock.Mock(return_value=RP.NO_CHROME))
        self.assertIn("Chrome", got)
        self.assertNotIn("signing in", got)


class FailuresReachTheChannel(_Setup):

    def test_a_crash_is_filed_with_its_traceback(self):
        self.step(check_login=mock.Mock(side_effect=CLOSED))
        self.assertEqual(len(self.reports), 1)
        r = self.reports[0]
        # The scheduled push's stage: notify_faults posts it to
        # #claudecorrections-and-requests and threads the traceback.
        self.assertEqual(r["stage"], "resume_push")
        self.assertEqual(r["office_key"], "drew")
        self.assertIn("window was closed", r["summary"])
        self.assertIn("Traceback", r["detail"])
        self.assertIn("has been closed", r["detail"])

    def test_a_login_that_never_reaches_the_office_is_filed(self):
        got = self.step(check_login=mock.Mock(return_value=1))
        self.assertEqual(got, "still needs signing in")
        self.assertEqual(len(self.reports), 1)

    def test_success_files_nothing(self):
        got = self.step(check_login=mock.Mock(return_value=0),
                        extension_installed=mock.Mock(return_value=True))
        self.assertEqual(got, "done")
        self.assertEqual(self.reports, [])

    def test_a_reporter_that_breaks_does_not_break_the_screen(self):
        with mock.patch("automations.icd_alerts.relay.report_fault",
                        side_effect=OSError("offline")):
            got = self.step(check_login=mock.Mock(side_effect=CLOSED))
        self.assertIn("window was closed", got)


class TheSummaryTable(unittest.TestCase):

    def _run(self, resume):
        lines = []
        ok = mock.Mock(return_value="already done")
        with mock.patch.multiple(F, _update=mock.Mock(return_value="up to date"),
                                 _boot_job=ok, _never_sleeps=ok,
                                 _saraplus=mock.Mock(return_value="already working"),
                                 _service_cloud=mock.Mock(
                                     return_value="not needed for this office"),
                                 _resume_push=resume):
            rc = F.run(log=lines.append)
        return rc, "\n".join(lines)

    def test_an_uncaught_step_crash_shows_its_message(self):
        rc, out = self._run(mock.Mock(side_effect=CLOSED))
        self.assertEqual(rc, 1)
        self.assertNotIn("failed (Error)", out)
        self.assertIn("failed — Error: Page.wait_for_timeout: Target page", out)
        self.assertIn("Something above still needs doing", out)

    def test_the_clean_path_is_unchanged(self):
        rc, out = self._run(mock.Mock(return_value="done"))
        self.assertEqual(rc, 0)
        self.assertIn("up to date", out)
        self.assertIn("already working", out)
        self.assertIn("All set. Nothing else to do.", out)
        self.assertNotIn("stopped", out)


NO_PROFILE = Error(
    "BrowserType.connect_over_cdp: Protocol error (Browser.setDownloadBehavior):"
    " Browser context management is not supported.\nCall log:\n"
    "  - <ws disconnected> ws://127.0.0.1:9247/devtools/browser/x code=1000")


class AWindowlessChromeIsBroughtBack(unittest.TestCase):
    """Drew, 2026-10-06: Lucy's Chrome was running on 9247 with every window
    closed. On a Mac that unloads the profile, and connect_over_cdp fails on
    Browser.setDownloadBehavior. Opening a window brings it back."""

    def setUp(self):
        self.p = mock.Mock()
        ctx = mock.Mock(pages=[mock.Mock()])
        self.browser = mock.Mock(contexts=[ctx])
        for name, val in (("_port_alive", mock.Mock(return_value=True)),
                          ("launch_chrome", mock.Mock(return_value=True)),
                          ("_log", mock.Mock())):
            pt = mock.patch.object(RP, name, val)
            pt.start()
            self.addCleanup(pt.stop)

    def connect(self, pages, side_effect):
        self.p.chromium.connect_over_cdp.side_effect = side_effect
        with mock.patch.object(RP, "_page_count", return_value=pages), \
             mock.patch.object(RP, "_open_window", return_value=True) as ow:
            got = RP._connect(self.p, background=False)
        return got, ow

    def test_no_window_gets_one_before_connecting(self):
        got, ow = self.connect(0, [self.browser])
        ow.assert_called_once()
        self.assertIs(got[0], self.browser)

    def test_a_chrome_with_a_window_is_left_alone(self):
        got, ow = self.connect(2, [self.browser])
        ow.assert_not_called()
        self.assertEqual(self.p.chromium.connect_over_cdp.call_count, 1)

    def test_the_error_itself_gets_a_window_and_one_retry(self):
        got, ow = self.connect(1, [NO_PROFILE, self.browser])
        ow.assert_called_once()
        self.assertEqual(self.p.chromium.connect_over_cdp.call_count, 2)
        self.assertIs(got[0], self.browser)

    def test_any_other_connect_error_is_not_retried(self):
        with self.assertRaises(Error):
            self.connect(1, [NO_CDP, self.browser])
        self.assertEqual(self.p.chromium.connect_over_cdp.call_count, 1)

    def test_a_fresh_launch_is_not_second_guessed(self):
        with mock.patch.object(RP, "_port_alive", return_value=False):
            got, ow = self.connect(0, [self.browser])
        ow.assert_not_called()

    def test_if_it_still_fails_the_screen_says_why(self):
        reason, hint = RP.explain_failure(NO_PROFILE)
        self.assertIn("no window open", reason)
        self.assertIn("Quit", hint)


if __name__ == "__main__":
    unittest.main()
