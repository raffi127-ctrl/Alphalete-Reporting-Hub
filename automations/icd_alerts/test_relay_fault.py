"""The laptop telling us what broke — and never making things worse by trying.

This code runs INSIDE exception handlers and at the end of a failed install.
Anything it raises replaces a diagnosable failure with a crash carrying no
message at all, which is worse than the silence it was built to end. So the
contract is blunt: report_fault returns a bool and raises nothing, ever.

The other half of the contract is what must NOT travel. The relay's promise is
that the SaraPlus login stays on the laptop; a crash message is the one place
a password reliably turns up in plain text, because patchright prints the
arguments it was called with.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import relay as R


class NeverRaises(unittest.TestCase):

    def test_not_enrolled_yet_is_not_an_error(self):
        with mock.patch.object(R, "_endpoint",
                               side_effect=R.RelayError("no install.json")):
            self.assertFalse(R.report_fault("install", "boom"))

    def test_a_dead_network_is_swallowed(self):
        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R, "_post", side_effect=OSError("no route")):
            self.assertFalse(R.report_fault("sweep", "boom"))

    def test_a_junk_reply_is_swallowed(self):
        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R, "_post", return_value="<html>nope</html>"):
            self.assertFalse(R.report_fault("sweep", "boom"))

    def test_a_good_reply_reports_success(self):
        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R, "_post", return_value='{"ok": true}'):
            self.assertTrue(R.report_fault("sweep", "boom"))


class HarmlessToAnOlderRelay(unittest.TestCase):
    """A fault must never be able to damage the numbers.

    The relay deployed on 2026-09-12 does not know what a fault is. Handed one
    with a top-level `day` it would fall past its knocks branch to
    `var records = body.records || {}` and upsert an EMPTY {} over that
    office's real credit checks for the day. Sending no top-level day makes
    that same script fail its own format check and do nothing, which is the
    only safe behaviour while offices update at their own pace.
    """

    def test_the_payload_carries_no_top_level_day(self):
        seen = {}

        def fake_post(url, data):
            import json
            seen.update(json.loads(data.decode()))
            return '{"ok": true}'

        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R.C, "creds", return_value={}), \
             mock.patch.object(R, "_post", fake_post):
            R.report_fault("sweep", "boom")
        self.assertNotIn("day", seen, "a top-level day would reach the "
                                      "records branch of an older relay")
        self.assertIn("day", seen["fault"])

    def test_the_payload_carries_no_records_or_sales(self):
        # Belt and braces: even reaching the records branch, there must be
        # nothing in it to write.
        seen = {}

        def fake_post(url, data):
            import json
            seen.update(json.loads(data.decode()))
            return '{"ok": true}'

        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R.C, "creds", return_value={}), \
             mock.patch.object(R, "_post", fake_post):
            R.report_fault("sweep", "boom")
        self.assertNotIn("records", seen)
        self.assertNotIn("sales", seen)


class NothingSecretTravels(unittest.TestCase):

    def _sent(self, summary, detail="", creds=None):
        seen = {}

        def fake_post(url, data):
            import json
            seen.update(json.loads(data.decode()))
            return '{"ok": true}'

        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "kash", "relay_key": "SECRETKEY123",
                "relay_url": "u"}), \
             mock.patch.object(R.C, "creds",
                               return_value=creds or {"email": "kash@palace.com",
                                                      "password": "Hunter2!!"}), \
             mock.patch.object(R, "_post", fake_post):
            R.report_fault("sweep", summary, detail)
        return seen["fault"]

    def test_the_saraplus_password_never_leaves(self):
        f = self._sent("login failed", "cmd: --password Hunter2!! --user x")
        self.assertNotIn("Hunter2!!", f["detail"])
        self.assertIn("[removed]", f["detail"])

    def test_the_relay_key_never_leaves_in_a_message(self):
        f = self._sent("posting to u?key=SECRETKEY123 failed")
        self.assertNotIn("SECRETKEY123", f["summary"])

    def test_any_email_is_removed_not_just_theirs(self):
        # A traceback can carry a CUSTOMER's address, and "no customer data
        # leaves the laptop" is worth keeping literally.
        f = self._sent("failed for someone.else@gmail.com")
        self.assertNotIn("gmail.com", f["summary"])
        self.assertIn("[email]", f["summary"])

    def test_a_secret_looking_kwarg_is_removed(self):
        f = self._sent("call(token=abc123, retries=2)")
        self.assertNotIn("abc123", f["summary"])

    def test_missing_creds_does_not_break_scrubbing(self):
        # At install time there may be no saved login yet.
        with mock.patch.object(R.C, "creds", side_effect=RuntimeError("none")):
            self.assertIn("[removed]", R._scrub("password=x9f3k2"))

    def test_detail_is_trimmed(self):
        f = self._sent("boom", "x" * 5000)
        self.assertLessEqual(len(f["detail"]), 1500)


if __name__ == "__main__":
    unittest.main()
