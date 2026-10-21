"""The week Submit click fails fast and retries once (2026-10-20: after the
switch-click fix, Submit still waited 30s per office on the rerun).

    python -m unittest automations.recruiting_report.test_submit_click
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from patchright.sync_api import TimeoutError as PWTimeout

from automations.recruiting_report import fetch_office as fo


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel
        self.first = self

    def input_value(self):
        return "10-11-2026"           # last week -> the submit path runs

    def click(self, **kw):
        assert kw.get("no_wait_after"), "Submit must leave the reload wait to expect_navigation (2026-10-21)"
        self.page.clicks += 1
        if self.page.clicks <= self.page.fail_n:
            raise PWTimeout("Locator.click: Timeout 10000ms exceeded.")


class _Nav:
    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False


class _Page:
    url = "https://applicantstream.com/index.cfm?p=701"

    def __init__(self, fail_n):
        self.fail_n, self.clicks = fail_n, 0

    def locator(self, sel):
        return _Loc(self, sel)

    def evaluate(self, *a, **k):
        return {"tried": [], "finalValues": {}}

    def expect_navigation(self, **kw):
        return _Nav()

    def wait_for_timeout(self, *a):
        pass

    def wait_for_function(self, *a, **k):
        return None


class SubmitClick(unittest.TestCase):

    def _run(self, fail_n):
        p = _Page(fail_n)
        with mock.patch.object(fo, "_JQUERY_GIVE_UP", True), \
                mock.patch.object(fo, "_FORM_DUMPED", True), \
                mock.patch.object(fo, "_dismiss_overlays"), \
                mock.patch.object(fo, "_ensure_on_retention_report"):
            fo._set_week_and_submit(p, dt.date(2026, 10, 18))
        return p

    def test_clean_click(self):
        self.assertEqual(self._run(0).clicks, 1)

    def test_one_miss_is_retried(self):
        self.assertEqual(self._run(1).clicks, 2)

    def test_two_misses_raise_fast(self):
        with self.assertRaises(PWTimeout):
            self._run(2)


if __name__ == "__main__":
    unittest.main()
