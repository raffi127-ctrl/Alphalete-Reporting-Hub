"""Box offices sign into My Service Cloud, as AT&T offices sign into SaraPlus.

Box, Energy Wells and NDS have no SaraPlus, so until now the knocks board was
their ENTIRE product -- nothing at all on the days their reps were selling
rather than knocking. This is the other half for Box.

These pin the two things that went wrong for every campaign that is not AT&T:
the question being asked of the MACHINE rather than the campaign, and a login
that is required being treated as optional.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from automations.icd_alerts import config as C
from automations.shared import servicecloud as SC

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()


class WhoSignsIntoIt(unittest.TestCase):

    def _with(self, campaigns):
        rows = [{"office_key": "o%d" % i, "campaign": c}
                for i, c in enumerate(campaigns)]
        return mock.patch.object(C, "enrollments", return_value=rows)

    def test_a_box_office_does(self):
        with self._with(["b2b_box"]):
            self.assertTrue(C.uses_servicecloud())

    def test_an_att_office_does_not(self):
        for camp in ("att", "b2b_att"):
            with self._with([camp]):
                self.assertFalse(C.uses_servicecloud(),
                                 "%s would be asked for a login it has no "
                                 "account for" % camp)

    def test_nds_and_energy_are_not_guessed_in(self):
        # They have no Service Cloud account either, and asking would repeat
        # exactly the mistake that cost Carlos his SaraPlus question.
        for camp in ("nds", "energy"):
            with self._with([camp]):
                self.assertFalse(C.uses_servicecloud())

    def test_carlos_runs_both_and_needs_both(self):
        with self._with(["b2b_box", "b2b_att"]):
            self.assertTrue(C.uses_servicecloud())
            self.assertTrue(C.uses_saraplus())

    def test_it_asks_any_campaign_not_the_first(self):
        # install() returns rows[0]; a machine whose Box campaign enrolled
        # second must still be asked.
        with self._with(["b2b_att", "b2b_box"]):
            self.assertTrue(C.uses_servicecloud())


class TheInstallerAsksForIt(unittest.TestCase):

    def test_there_is_a_question(self):
        self.assertIn("def ask_for_servicecloud(", SETUP)

    def test_it_is_required(self):
        i = SETUP.index("def ask_for_servicecloud(")
        self.assertIn("required=True", SETUP[i:i + 700],
                      "the login a Box office sells through is optional")

    def test_it_asks_about_the_campaign_not_the_machine(self):
        i = SETUP.index("SERVICECLOUD_CAMPAIGNS")
        seg = SETUP[max(0, i - 400):i + 200]
        self.assertIn("this_campaign", seg,
                      "it asks the machine, which answers for whichever "
                      "campaign enrolled first")


class ALoginThatLandsOnTheResetPageIsNotALogin(unittest.TestCase):
    """SaraPlus taught this the expensive way: a session that lands on the
    password page still renders, still parses, and reports every rep at zero
    -- which reads as a quiet day rather than a broken account."""

    def test_the_reset_page_is_recognised(self):
        self.assertTrue(SC._is_password_reset(
            "https://myservicecloud.net/user/index/request-password-reset"))
        self.assertFalse(SC._is_password_reset("https://myservicecloud.net/"))

    def test_signed_in_is_false_while_a_password_box_is_on_screen(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/sign-in"
        page.query_selector.return_value = object()      # password box present
        self.assertFalse(SC.signed_in(page))

    def test_signed_in_is_true_once_it_is_gone(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/dashboard"
        page.query_selector.return_value = None
        self.assertTrue(SC.signed_in(page))

    def test_a_refused_login_says_what_the_office_can_do(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/sign-in"
        page.query_selector.return_value = object()
        with self.assertRaises(SC.AccountProblem) as e:
            SC.sign_in(page, "someone@example.com", "x", log=lambda *_: None)
        msg = str(e.exception)
        self.assertIn("someone@example.com", msg)
        self.assertIn("installer", msg,
                      "the message does not tell the office how to fix it")


if __name__ == "__main__":
    unittest.main()
