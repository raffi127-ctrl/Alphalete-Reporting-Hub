"""Noticing that somebody pressed Save.

2026-11-23: this caught the employment record (202s) and the user profile
(25s), then sat through a tax & bank save Megan made in the very window it
was watching. The record went Active and the run was still printing "I am
watching for it". Unattended, that is Lucy saving a payroll record and not
knowing whether it landed.
"""
from __future__ import annotations

import unittest

from automations.apex_new_starts import drive


class _Res:
    def __init__(self, url, method="POST", status=200):
        self.url, self.status = url, status
        self.request = type("R", (), {"method": method})()


class _Page:
    """Replays responses into whatever the watcher registers."""

    def __init__(self, url, responses):
        self.url = url
        self._responses = list(responses)
        self._on = None
        self.waited = 0

    def on(self, _event, fn):
        self._on = fn

    def remove_listener(self, _event, _fn):
        self._on = None

    def wait_for_timeout(self, ms):
        self.waited += ms
        if self._responses and self._on:
            self._on(self._responses.pop(0))


HOST = "https://apex.herbjoyent.com"


class WhatCountsAsASave(unittest.TestCase):

    def _run(self, responses, apex_id="123"):
        said = []
        page = _Page(HOST + "/employees/123/bank-info", responses)
        ok = drive.wait_for_save(page, apex_id, seconds=4, log=said.append)
        return ok, " ".join(said)

    def test_the_employees_own_url_still_counts(self):
        ok, said = self._run([_Res(HOST + "/employees/123/employment-record")])
        self.assertTrue(ok)
        self.assertIn("saved after", said)

    def test_the_last_save_counts_even_off_the_employee_path(self):
        """The save that moves somebody off Pending need not post under
        /employees/<pending id> at all -- which is exactly what was missed."""
        ok, _said = self._run([_Res(HOST + "/onboarding/complete/987")])
        self.assertTrue(ok)

    def test_the_url_that_counted_is_printed(self):
        """A watcher that says only "saved" cannot be checked by the next
        person who has to work out why it did not."""
        ok, said = self._run([_Res(HOST + "/onboarding/complete/987")])
        self.assertTrue(ok)
        self.assertIn("/onboarding/complete/987", said)

    def test_somebody_elses_host_is_not_a_save(self):
        """A record reported saved that is not is worse than a missed one:
        it is a person nobody goes back to."""
        ok, _said = self._run([_Res("https://analytics.example.com/beacon")])
        self.assertFalse(ok)

    def test_a_get_is_not_a_save(self):
        ok, _said = self._run([_Res(HOST + "/employees/123", method="GET")])
        self.assertFalse(ok)

    def test_a_refused_post_is_not_a_save(self):
        """Apex answering 400 to a bad tab is the opposite of a save."""
        ok, _said = self._run([_Res(HOST + "/employees/123", status=400)])
        self.assertFalse(ok)

    def test_giving_up_says_whether_anything_went_past(self):
        """A wait that saw requests it did not count is a different problem
        from one that saw nothing, and only the first is a bug here."""
        _ok, said = self._run([_Res("https://analytics.example.com/beacon")])
        self.assertIn("no save seen", said)
        self.assertIn("other request", said)

    def test_a_silent_wait_says_nothing_about_other_requests(self):
        _ok, said = self._run([])
        self.assertNotIn("other request", said)


if __name__ == "__main__":
    unittest.main()
