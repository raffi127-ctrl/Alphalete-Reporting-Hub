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

    def test_nds_is_an_att_campaign(self):
        """It sat on the no-SaraPlus list because it is not the FIBER
        campaign, and "not fiber" was read as "not AT&T" -- its own Tableau
        workbook is NDS-SNRES-ATT-OOFWorkbook (Megan 2026-09-15). An NDS
        office was never asked for a login and could never have had a credit
        check or a sale read, with nothing reporting a fault."""
        self.assertTrue(S.uses_saraplus("nds"))

    def test_box_and_energy_are_not(self):
        for key in ("b2b_box", "energy"):
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
        """The RULE, not the line. This asserted `if _C.uses_saraplus():`,
        which asks the MACHINE -- and on a two-campaign machine that answers
        for the FIRST enrollment. Carlos's Box campaign was first, so his B2B
        AT&T install was told it needed no SaraPlus login and never asked for
        one (2026-09-15). The decision now comes from the campaign being
        installed, and pinning the old line would have defended the bug."""
        self.assertIn("no SaraPlus needed", SETUP)
        # Decided from the record step 5 wrote, not from the machine.
        i = SETUP.index("no SaraPlus needed")
        before = SETUP[max(0, i - 900):i]
        self.assertIn("this_campaign", before)
        self.assertNotIn("_C.uses_saraplus()", before)

    def test_the_sweep_does_not_try_to_read_saraplus(self):
        """A machine with no AT&T campaign never signs in.

        Asserted on behaviour rather than on one line: the check moved from
        "is this office AT&T" to "does this MACHINE hold an AT&T enrollment"
        when an office could run two campaigns, and the old assertion pinned
        the implementation rather than the rule.
        """
        marker = "sales come from elsewhere"
        self.assertIn(marker, RUN)
        # It must find a SaraPlus enrollment before reading anything...
        self.assertLess(RUN.index("C.NO_SARAPLUS"),
                        RUN.index("sara_read.read_day"))
        # ...OFF THE SHARED LIST, never a second copy of it. run.py used to
        # spell the exclusions out inline, so moving NDS onto SaraPlus in
        # config.py would have left the sweep still skipping it: the office
        # asked for a login, saved it, and it was never used (2026-09-15).
        self.assertNotIn('("nds", "energy", "b2b_box")', RUN)
        # ...and returning clean, not as a failure: nothing is wrong.
        after = RUN[RUN.index(marker):]
        self.assertIn("return 0", after[:200])

    def test_the_campaign_reaches_the_installer(self):
        # Without this every office installs as AT&T and a Box machine spends
        # its life signing into an account that does not exist.
        self.assertIn("campaign: v('campaign', 'att')", GS)


if __name__ == "__main__":
    unittest.main()


class MoreThanOneCampaignOnOneMachine(unittest.TestCase):
    """An office enrols each campaign independently, on the same computer.

    Megan 2026-09-15: "if an ICD has multi campaigns, they can enroll them or
    not independently and we always are able to grab the correct one."

    A campaign IS a reporting unit here -- its own relay key, channels,
    cadence and board -- so each is its own enrollment, and the machine holds
    them side by side.
    """

    def test_each_campaign_gets_its_own_readable_key(self):
        from automations.icd_signup import store
        first = store.office_key_for("Ryan McSpadden", set(), "b2b_box")
        second = store.office_key_for("Ryan McSpadden", {first}, "att")
        self.assertEqual(first, "ryan")
        self.assertEqual(second, "ryan-att")
        # A number would tell nobody which campaign it is, and this key shows
        # up in the approve command, the relay row and their setup code.
        self.assertNotIn("ryan2", (first, second))

    def test_a_second_install_adds_rather_than_replaces(self):
        src = (ROOT / "automations/icd_alerts/dist/setup.py").read_text()
        self.assertIn("ADDING A CAMPAIGN, NOT REPLACING THE MACHINE", src)
        self.assertNotIn("existing.update(rec)", src,
                         "the installer still overwrites the whole record")

    def test_the_sweep_walks_every_campaign(self):
        src = (ROOT / "automations/icd_alerts/run.py").read_text()
        self.assertIn("for rec in rows_of:", src)
        # One failing campaign must not cost the others.
        self.assertIn("worst = 1", src)
        self.assertIn("continue", src)

    def test_each_campaign_relays_under_its_own_key(self):
        import inspect
        from automations.icd_alerts import relay as R
        self.assertIn("office_key", inspect.signature(R.send_knocks).parameters)
        self.assertIn("office_key", inspect.signature(R.send).parameters)

    def test_the_form_tells_them_a_second_is_possible(self):
        self.assertIn("Run more than one campaign?", FORM)
