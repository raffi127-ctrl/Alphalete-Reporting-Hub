"""Every fault post says on top whether anybody has to do anything.

Eve could not tell a post she had to act on from one that clears itself
(2026-10-06).
"""
import unittest

from automations.icd_alerts import post as P


class WhatToDo(unittest.TestCase):

    def test_a_code_wall_goes_to_the_office(self):
        line = P.what_to_do("Eveliz's Local Office",
                            "AccountProblem: SaraPlus wants to confirm this "
                            "computer with a code it emails you.")
        self.assertIn("send this to Eveliz's Local Office", line)

    def test_a_refused_password_goes_to_the_office(self):
        line = P.what_to_do("X", "AccountProblem: SaraPlus did not accept "
                                 "that email and password.")
        self.assertIn("send this to X", line)

    def test_ours_goes_to_claude(self):
        line = P.what_to_do("X", "AccountProblem: SaraPlus sent the login page "
                                 "back without saying why")
        self.assertIn("paste it to Claude. It won't", line)

    def test_anything_else_is_nothing_to_do(self):
        line = P.what_to_do("X", "TimeoutError: page.goto timed out")
        self.assertIn("Nothing to do", line)
        self.assertIn("within an hour", line)


if __name__ == "__main__":
    unittest.main()
