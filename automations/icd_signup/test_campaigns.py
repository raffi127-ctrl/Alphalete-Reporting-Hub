"""What an office gets depends on the campaign it runs.

Megan 2026-09-15: "At&t is the only campaign on sara plus" and "for
Box/energywell we need LucyECO to only ask them to enroll in the knock
reports from their machines".

Credit checks and sales come from SaraPlus. A Box, Energy Wells or NDS office
has no SaraPlus account at all -- so those reports are not switched off for
them, they were never theirs. The failure this prevents is an install that
dies at the login step with an owner certain they typed it right, because we
asked for a password to an account that does not exist.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from automations.icd_signup import schema as S

ROOT = pathlib.Path(__file__).resolve().parents[2]
FORM = (ROOT / "icd_signup" / "app.py").read_text()
SETUP = (ROOT / "automations/icd_alerts/dist/setup.py").read_text()
RUN = (ROOT / "automations/icd_alerts/run.py").read_text()
GS = (ROOT / "resources/icd-alerts-relay.gs").read_text()


class WhoIsOnSaraPlus(unittest.TestCase):

    def test_att_campaigns_are(self):
        self.assertTrue(S.uses_saraplus("att"))
        self.assertTrue(S.uses_saraplus("b2b_att"))

    def test_box_energy_and_nds_are_not(self):
        for key in ("b2b_box", "energy", "nds"):
            self.assertFalse(S.uses_saraplus(key), key)

    def test_an_unknown_campaign_asks_rather_than_skipping(self):
        """A campaign nobody has told this module about should ask for the
        login and be TOLD it does not work, rather than silently never
        collecting credit checks that were supposed to arrive."""
        self.assertTrue(S.uses_saraplus("something_new"))

    def test_an_office_with_no_campaign_recorded_is_att(self):
        # Every office enrolled before campaigns existed was on AT&T.
        # Defaulting the other way would take Kash's and Cyrus's credit checks
        # away the moment they updated.
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "install", return_value={}):
            self.assertEqual(C.campaign(), "att")
            self.assertTrue(C.uses_saraplus())


class TheyAreNeverAskedForWhatTheyCannotHave(unittest.TestCase):

    def test_the_form_hides_the_alert_channels(self):
        self.assertIn("if S.uses_saraplus(campaign):", FORM)

    def test_the_installer_skips_the_saraplus_login(self):
        self.assertIn("if _C.uses_saraplus():", SETUP)
        self.assertIn("no SaraPlus needed", SETUP)

    def test_the_sweep_does_not_try_to_read_saraplus(self):
        self.assertIn("if not C.uses_saraplus():", RUN)
        # and it returns clean, not as a failure -- nothing is wrong
        after = RUN[RUN.index("if not C.uses_saraplus():"):]
        self.assertIn("return 0", after[:400])

    def test_the_campaign_reaches_the_installer(self):
        # Without this every office installs as AT&T and a Box machine spends
        # its life signing into an account that does not exist.
        self.assertIn("campaign: v('campaign', 'att')", GS)


if __name__ == "__main__":
    unittest.main()
