"""Every office is asked for its OwnerVille login, not just SaraPlus ones.

The OwnerVille question lived inside ask_for_login(), which only runs for
SaraPlus campaigns. When the SaraPlus step learned to skip itself for Box,
Energy Wells and NDS, it took the OwnerVille question with it.

Those are exactly the campaigns where the knocks board is the ONLY thing the
office gets, and OwnerVille is what reads it. Carlos installed on 2026-09-15,
was never shown an OwnerVille box, and was told "All set" by an install that
could not read a single number.
"""
from __future__ import annotations

import pathlib
import unittest

SETUP = (pathlib.Path(__file__).resolve().parent / "dist" / "setup.py").read_text()


class AKnocksOnlyOfficeIsAskedForOwnerville(unittest.TestCase):

    def test_the_skip_branch_still_asks(self):
        i = SETUP.index("no SaraPlus needed, skipping that login")
        after = SETUP[i:i + 600]
        self.assertIn("ask_for_ownerville", after,
                      "skipping SaraPlus also skips the only login this "
                      "office has")

    def test_it_is_required_there(self):
        i = SETUP.index("no SaraPlus needed, skipping that login")
        after = SETUP[i:i + 600]
        self.assertIn("required=True", after,
                      "the one login a knocks-only office needs is optional")

    def test_the_ask_is_reachable_on_its_own(self):
        self.assertIn("def ask_for_ownerville(", SETUP)

    def test_saraplus_offices_still_get_asked(self):
        i = SETUP.index("def ask_for_login(")
        body = SETUP[i:i + 2000]
        self.assertIn("ask_for_ownerville", body)


class MissingCredentialsAreNotAPass(unittest.TestCase):
    """check_ownerville() returned True when there was no credentials file at
    all -- "they skipped it, nothing to verify". True for a SaraPlus office,
    whose alerts work regardless. False for an office whose entire product is
    the board."""

    def test_a_knocks_only_office_with_no_login_fails_the_check(self):
        i = SETUP.index("def check_ownerville(")
        body = SETUP[i:i + 1400]
        self.assertIn("uses_saraplus", body,
                      "a missing OwnerVille login passes for every office")
        self.assertIn("return False", body)


if __name__ == "__main__":
    unittest.main()
