"""The OwnerVille window (2026-10-21): the box hands off to it, the sweep offers
it ahead of the password box, finish_setup runs it only on a failed sign-in."""
import unittest
from unittest import mock

from automations.icd_alerts import autoprompt, finish_setup as F, ov_signin


class OvSigninTest(unittest.TestCase):
    def test_rqst_now_reads_url_or_link(self):
        page = mock.Mock(url="https://v2.ownerville.com/index.cfm?p=2&rqst=ABC")
        self.assertTrue(ov_signin._rqst_now(page))
        page = mock.Mock(url="https://ownerville.com/"); page.evaluate.return_value = ""
        self.assertFalse(ov_signin._rqst_now(page))
        page.evaluate.return_value = "index.cfm?rqst=XYZ"
        self.assertTrue(ov_signin._rqst_now(page))

    def test_autoprompt_knows_the_window(self):
        self.assertEqual(autoprompt.SYSTEMS["ownerville"]["module"], "automations.icd_alerts.ov_signin")

    def test_finish_setup_skips_when_nothing_is_held(self):
        with mock.patch("automations.icd_alerts.ov_read.held_on_lock", return_value=False), \
             mock.patch("automations.icd_alerts.ov_read.ov_hold_message", return_value=""), \
             mock.patch("automations.icd_alerts.ov_signin.run") as run:
            self.assertEqual(F._ownerville(lambda *_: None), "nothing to do")
        run.assert_not_called()

    def test_finish_setup_opens_the_window_on_a_failed_signin(self):
        with mock.patch("automations.icd_alerts.ov_read.held_on_lock", return_value=False), \
             mock.patch("automations.icd_alerts.ov_read.ov_hold_message", return_value="failed"), \
             mock.patch("automations.icd_alerts.ov_signin.run", return_value=0) as run:
            self.assertEqual(F._ownerville(lambda *_: None), "done")
        run.assert_called_once()

    def test_finish_setup_never_opens_the_window_on_a_lock(self):
        with mock.patch("automations.icd_alerts.ov_read.held_on_lock", return_value=True), \
             mock.patch("automations.icd_alerts.ov_signin.run") as run:
            self.assertIn("LOCKED", F._ownerville(lambda *_: None))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
