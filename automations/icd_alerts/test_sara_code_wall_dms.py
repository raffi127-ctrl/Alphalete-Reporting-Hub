"""The SaraPlus emailed-code wall reaches the person who can clear it.

Eveliz's iMac hit the wall from 2026-10-03 to 10-06 and every report went to
the corrections room as a laptop fault ("the office was not asked to send
anything"). Nobody at the machine was told. Now it is filed as a sign-in.
"""
import unittest

from automations.icd_alerts import post as P
from automations.icd_alerts import run as RUN
from automations.icd_alerts import sara_read
from automations.shared import saraplus as S


class CodeWallIsASignIn(unittest.TestCase):

    def _owner_problem(self, raw):
        try:
            try:
                raise raw
            except S.SaraError as e:
                raise sara_read._as_owner_problem(e) from e
        except sara_read.AccountProblem as out:
            return out

    def test_the_code_wall_is_filed_as_a_sign_in(self):
        e = self._owner_problem(S.SaraPasscodeWall("wants an emailed code"))
        self.assertTrue(RUN._is_code_wall(e))

    def test_a_refused_password_stays_a_sweep_fault(self):
        e = sara_read.AccountProblem(
            "SaraPlus did not accept that email and password.")
        self.assertFalse(RUN._is_code_wall(e))

    def test_the_dm_does_not_blame_the_password(self):
        spec = P.SYSTEMS["saraplus"]
        text = spec["why"] + spec["how"]
        self.assertNotIn("changed", text)
        self.assertNotIn("new password", text)
        self.assertIn("code", text)
        self.assertIn(P.FINISH_SETUP_PAGE, text)


if __name__ == "__main__":
    unittest.main()
