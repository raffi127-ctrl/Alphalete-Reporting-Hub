"""An install that cannot report must never say "All set".

THREE SEPARATE FAILURES ON 2026-09-15 ALL ENDED THE SAME WAY. A campaign
branch skipped the only login the office had; a missing credentials file read
as "nothing to verify"; a sleep setting went unchecked. Each was found by a
person noticing an empty board, and each was patched where it was found --
which is precisely how the next one gets missed.

So these test the RULE rather than the three bugs: for every campaign we
support, an install missing what that campaign needs is refused, and one that
has it is not.
"""
from __future__ import annotations

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()
RUN = (HERE / "run.py").read_text()


def _install_problems(tmp, sara, files, awake=None):
    """Run the real install_problems() against a fake config dir."""
    src, keep = [], False
    for line in SETUP.splitlines():
        if line.startswith("def install_problems("):
            keep = True
        elif keep and line.startswith("def ") and "install_problems" not in line:
            break
        if keep:
            src.append(line)
    for f in files:
        (tmp / f).write_text("{}")
    ns = {"CONFIG_DIR": tmp}
    exec("\n".join(src), ns)

    # PATCH THE ATTRIBUTE, NOT sys.modules. `from automations.icd_alerts
    # import config` reads the attribute off the already-imported package, so
    # a sys.modules entry is simply ignored -- which made these three pass on
    # their own and fail under discover, where something else had imported the
    # package first. An order-dependent test is worse than no test.
    from unittest import mock
    with mock.patch("automations.icd_alerts.config.uses_saraplus",
                    return_value=sara):
        return ns["install_problems"](awake)


class EveryCampaignIsCheckedForWhatItActuallyNeeds(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    # --- the campaigns with NO SaraPlus: the board is everything ------------
    def test_knocks_only_office_with_no_ownerville_is_blocked(self):
        blocking, _ = _install_problems(
            self.tmp, sara=False, files=["install.json"])
        self.assertTrue(blocking, "a Box/Energy/NDS office with no "
                                  "OwnerVille login was told it was fine")
        self.assertIn("OwnerVille", " ".join(blocking))

    def test_knocks_only_office_with_ownerville_is_fine(self):
        blocking, _ = _install_problems(
            self.tmp, sara=False,
            files=["install.json", "ownerville-creds.json"])
        self.assertEqual(blocking, [])

    def test_a_knocks_only_office_does_not_need_saraplus(self):
        blocking, _ = _install_problems(
            self.tmp, sara=False,
            files=["install.json", "ownerville-creds.json"])
        self.assertNotIn("SaraPlus", " ".join(blocking))

    # --- the SaraPlus campaigns: OwnerVille is a real but partial loss ------
    def test_saraplus_office_with_no_saraplus_is_blocked(self):
        blocking, _ = _install_problems(
            self.tmp, sara=True, files=["install.json"])
        self.assertIn("SaraPlus", " ".join(blocking))

    def test_saraplus_office_missing_ownerville_is_a_note_not_a_block(self):
        blocking, notes = _install_problems(
            self.tmp, sara=True,
            files=["install.json", "saraplus-creds.json"])
        self.assertEqual(blocking, [],
                         "an AT&T office lost its alerts over a missing "
                         "knocks login")
        self.assertIn("knocks", " ".join(notes))

    # --- things that are true for everyone ---------------------------------
    def test_missing_settings_block_everyone(self):
        for sara in (True, False):
            blocking, _ = _install_problems(
                self.tmp, sara=sara,
                files=["saraplus-creds.json", "ownerville-creds.json"])
            self.assertTrue(blocking)

    def test_a_sleepy_machine_is_a_note(self):
        _, notes = _install_problems(
            self.tmp, sara=False,
            files=["install.json", "ownerville-creds.json"],
            awake={"never_sleeps": False})
        self.assertIn("sleep", " ".join(notes))


class TheFinalMessageIsDerivedNotRemembered(unittest.TestCase):

    def test_all_set_is_behind_the_check(self):
        """"All set" must never be printed without first asking whether the
        install can actually work.

        ORDERING, NOT A CHARACTER WINDOW. This used to look back 1500 bytes
        from the "All set" line, which made it fail the moment a comment was
        added above it (2026-09-16) -- a test that breaks on prose is a test
        people learn to edit rather than read.
        """
        said = SETUP.index('say("  %s%sAll set.%s"')
        checked = SETUP.index("install_problems(")
        self.assertLess(checked, said,
                        '"All set" is printed without asking whether the '
                        "install can work")

    def test_the_all_set_line_is_reached_through_the_check(self):
        """And the answer has to be USED, not merely computed."""
        said = SETUP.index('say("  %s%sAll set.%s"')
        between = SETUP[SETUP.index("install_problems("):said]
        self.assertIn("blocking", between,
                      "install_problems runs and its answer is dropped")

    def test_an_unworkable_install_reports_itself(self):
        self.assertIn("_report_setup_incomplete", SETUP)
        self.assertIn("setup finished but cannot report", SETUP)


class TheAgentSaysSoToo(unittest.TestCase):
    """Install-time is only half. Carlos's machine would have ticked every two
    minutes logging "no OwnerVille login saved" to a file on his own desk."""

    def test_a_knocks_only_office_with_no_login_reports_upstream(self):
        i = RUN.index("no OwnerVille login saved")
        after = RUN[i:i + 700]
        self.assertIn("uses_saraplus", after)
        self.assertIn("_report(", after,
                      "the agent still logs this locally and tells nobody")

    def test_a_saraplus_office_stays_quiet_about_it(self):
        # Their alerts work; a fault every tick would be noise.
        i = RUN.index("no OwnerVille login saved")
        after = RUN[i:i + 700]
        self.assertLess(after.index("uses_saraplus"), after.index("_report("),
                        "the report fires before the campaign is checked, so "
                        "every AT&T office would raise it too")


if __name__ == "__main__":
    unittest.main()


class AKnocksOnlyOfficeCanBeApproved(unittest.TestCase):
    """The Office Channels request columns are written by the relay when a
    machine posts its RECORDS. A Box, Energy Wells or NDS office never posts
    records -- it has no SaraPlus -- so it relayed its board all day and still
    had no row there. No row meant it could not be approved, and an office
    that cannot be approved can never post. Carlos, 2026-09-15.
    """

    APPROVE = (HERE / "approve.py").read_text()

    def test_cmd_knocks_falls_back_to_the_signup(self):
        i = self.APPROVE.index("def cmd_knocks(")
        body = self.APPROVE[i:i + 2500]
        self.assertIn("signup_store", body,
                      "a knocks-only office with no relayed row is still "
                      "refused")

    def test_the_approval_creates_the_row_rather_than_refusing(self):
        i = self.APPROVE.index("def _write_knocks_approval(")
        body = self.APPROVE[i:i + 1800]
        self.assertIn("append_row", body)
        self.assertNotIn("raise SystemExit", body,
                         "it still refuses when the office has no row, which "
                         "is exactly the office that needs one made")
