"""A session that times out mid-run is named as that, not as a missing
checkbox (2026-10-19: 6 of 17 offices read "Group-by-Original-Subject
checkbox not found" after the AppStream login timed out at ~02:30).

    python -m unittest automations.indeed_source_report.test_logged_out
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.indeed_source_report import fetch

LOGGED_OUT = "Your login is timed out. Please Login again."


class _Page:
    url = "https://applicantstream.com/index.cfm?p=702&rqst=X"

    def __init__(self, text):
        self.text = text
        self.passes = 0

    def evaluate(self, _js):
        return self.text

    def goto(self, *a, **k):
        self.passes += 1

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass


class LoggedOut(unittest.TestCase):

    def test_logged_out_page_raises_logged_out(self):
        with self.assertRaises(fetch.AppStreamLoggedOut):
            fetch._one_pass(_Page(LOGGED_OUT), "X", "10-18-2026",
                            "10-18-2026", 1000)

    def test_no_retry_on_a_dead_session(self):
        page = _Page(LOGGED_OUT)
        with self.assertRaises(fetch.AppStreamLoggedOut):
            fetch.source_report(page, "X", "10-18-2026", "10-18-2026",
                                attempts=2)
        self.assertEqual(page.passes, 1)

    def test_no_table_error_names_it(self):
        e = fetch._no_table_error(_Page(LOGGED_OUT))
        self.assertIsInstance(e, fetch.AppStreamLoggedOut)

    def test_relogin_fails_loud_when_saved_session_dead(self):
        from automations.shared import tableau_patchright as tp
        page = _Page("")
        page.context = object()
        with mock.patch.object(tp, "_reuse_appstream_storage_state",
                               return_value=False):
            with self.assertRaises(fetch.AppStreamLoggedOut):
                fetch.relogin(page)


if __name__ == "__main__":
    unittest.main()
