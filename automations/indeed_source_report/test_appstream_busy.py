"""AppStream's own error page gets a late second chance, not a 2.5s re-ask.

Run:  python -m unittest automations.indeed_source_report.test_appstream_busy

WHAT THIS GUARDS (2026-10-10). Rafael Hidalgo (11280) dropped at 1 AM again
after the 10-09 five-minute table wait — and the new "no table" log line showed
why: AppStream answered both posts with "The request can not be processed!
... Please try again later". Overnight-only; 1 PM always pulls him fine.
"""
from __future__ import annotations

import unittest

from automations.indeed_source_report import fetch, run


class _Page:
    def __init__(self, body):
        self.url = "https://applicantstream.com/index.cfm?p=702&rqst=x"
        self._body = body
        self.slept = []

    def evaluate(self, js):
        return self._body

    def query_selector_all(self, sel):
        return []

    def wait_for_timeout(self, ms):
        self.slept.append(ms)


ERROR_PAGE = ("The request can not be processed! We are sorry but we are "
              "unable to process your request at this time. Please try again later.")


class TheErrorPageIsRecognised(unittest.TestCase):

    def _scrape(self, body):
        page = _Page(body)
        orig = fetch._one_pass
        fetch._one_pass = lambda page, *a: (_ for _ in ()).throw(
            fetch._no_table_error(page))       # a pass that found no table
        try:
            with self.assertRaises(Exception) as cm:
                fetch.source_report(page, "tok", "10-01-2026", "10-10-2026")
        finally:
            fetch._one_pass = orig
        return cm.exception, page

    def test_error_page_raises_busy_and_waits_a_minute(self):
        e, page = self._scrape(ERROR_PAGE)
        self.assertIsInstance(e, fetch.AppStreamBusy)
        self.assertEqual(page.slept, [fetch.BUSY_PAUSE_MS])

    def test_any_other_blank_page_keeps_the_old_error(self):
        e, page = self._scrape("Source Report  Start Date  End Date")
        self.assertNotIsInstance(e, fetch.AppStreamBusy)
        self.assertEqual(page.slept, [2500])


class RefusedOfficesGoAgainAtTheEnd(unittest.TestCase):

    def test_busy_offices_come_back_after_the_roster(self):
        page, busy = _Page(""), []
        seen = []
        for t in run._with_late_retry([("1", "A"), ("2", "B"), ("3", "C")],
                                      busy, page, pause_ms=5):
            seen.append(t)
            if t == ("2", "B") and t not in busy:
                busy.append(t)          # what main()'s except branch does
        self.assertEqual(seen, [("1", "A"), ("2", "B"), ("3", "C"), ("2", "B")])
        self.assertEqual(page.slept, [5])

    def test_clean_pass_never_pauses(self):
        page = _Page("")
        seen = list(run._with_late_retry([("1", "A")], [], page, pause_ms=5))
        self.assertEqual(seen, [("1", "A")])
        self.assertEqual(page.slept, [])


if __name__ == "__main__":
    unittest.main()
