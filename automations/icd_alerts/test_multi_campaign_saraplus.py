"""A machine running two campaigns must be asked about the right one.

install() returns rows[0] -- the FIRST enrollment -- and uses_saraplus() was
built on it. On a machine with one campaign that is correct. On Carlos's, his
Box campaign was first, so his B2B AT&T install asked the machine "do you use
SaraPlus?", was told no, and never asked him for the login that campaign
needs. His credit checks could never be read, and the channel he named sat
empty with nothing to explain it (2026-09-15).

Same shape as every other failure that day: a per-campaign fact answered by a
machine-wide question.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from automations.icd_alerts import config as C

SETUP = (pathlib.Path(__file__).resolve().parent / "dist" / "setup.py").read_text()


class AnyCampaignOnTheMachineCounts(unittest.TestCase):

    def _with(self, campaigns):
        rows = [{"office_key": "o%d" % i, "campaign": c}
                for i, c in enumerate(campaigns)]
        return mock.patch.object(C, "enrollments", return_value=rows)

    def test_box_first_then_b2b_att(self):
        # Carlos exactly: the first record says no, the second says yes.
        with self._with(["b2b_box", "b2b_att"]):
            self.assertTrue(C.uses_saraplus(),
                            "the machine reads its FIRST campaign, so the "
                            "SaraPlus half of the agent never runs")

    def test_b2b_att_first_then_box(self):
        with self._with(["b2b_att", "b2b_box"]):
            self.assertTrue(C.uses_saraplus())

    def test_two_campaigns_neither_on_saraplus(self):
        with self._with(["b2b_box", "nds"]):
            self.assertFalse(C.uses_saraplus())

    def test_a_single_box_office_is_unchanged(self):
        with self._with(["b2b_box"]):
            self.assertFalse(C.uses_saraplus())

    def test_a_single_att_office_is_unchanged(self):
        with self._with(["att"]):
            self.assertTrue(C.uses_saraplus())

    def test_an_office_enrolled_before_campaigns_existed(self):
        # No campaign recorded means AT&T -- every one of them was.
        with self._with([{}.get("x", "")]):
            self.assertTrue(C.uses_saraplus())


class TheInstallerAsksAboutTheCampaignItIsInstalling(unittest.TestCase):

    def test_it_uses_the_record_it_just_wrote(self):
        i = SETUP.index("no SaraPlus needed, skipping that login")
        before = SETUP[max(0, i - 900):i]
        self.assertIn("this_campaign", before,
                      "the installer still asks the MACHINE, which answers "
                      "for its first enrollment")

    def test_it_does_not_ask_the_machine(self):
        i = SETUP.index("no SaraPlus needed, skipping that login")
        before = SETUP[max(0, i - 900):i]
        self.assertNotIn("_C.uses_saraplus()", before)


if __name__ == "__main__":
    unittest.main()
