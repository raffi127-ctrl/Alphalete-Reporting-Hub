"""The accent fold every name matcher in the new-start family shares.

Each case below was a live divergence between four hand-written copies
(measured 2026-09-26). The Đ case is the one that was actually broken in three
of them.
"""
import unittest

from automations.shared.names import fold_accents


class KeepsTheLetterUnderTheMark(unittest.TestCase):
    def test_the_bug_three_of_four_copies_had(self):
        """NFKD does not split Đ into D + a mark — the stroke is inside the
        codepoint — so "drop non-ASCII" took the whole letter and "Anh Đinh"
        folded to 'anh inh', matching nothing."""
        self.assertEqual(fold_accents("Anh Đinh"), "Anh dinh")
        self.assertEqual(fold_accents("đinh"), "dinh")

    def test_the_other_undecomposable_letters(self):
        self.assertEqual(fold_accents("Søren"), "Soren")
        self.assertEqual(fold_accents("Łukasz"), "lukasz")
        self.assertEqual(fold_accents("Straße"), "Strasse")
        self.assertEqual(fold_accents("Æsop"), "aesop")

    def test_ordinary_combining_accents(self):
        self.assertEqual(fold_accents("Durañona"), "Duranona")
        self.assertEqual(fold_accents("De'Avioñ Allen"), "De'Avion Allen")
        self.assertEqual(fold_accents("José Ruiz"), "Jose Ruiz")

    def test_it_only_removes_marks(self):
        """Case, spacing and punctuation are the caller's business — they
        disagree about punctuation for real reasons."""
        self.assertEqual(fold_accents("  De'Avion  ALLEN-Jones "),
                         "  De'Avion  ALLEN-Jones ")

    def test_empty_and_none(self):
        self.assertEqual(fold_accents(""), "")
        self.assertEqual(fold_accents(None), "")


class EveryCallerAgreesOnTheFold(unittest.TestCase):
    def test_the_four_name_matchers_all_resolve_dinh(self):
        from automations.bg_check_sync import parse as BG
        from automations.digi_docs import namematch as NM
        from automations.new_start_followup import roster as NSF
        from automations.new_starts_box import names as NB
        for fn in (BG.norm, NM.norm, NSF._norm, NB.norm):
            self.assertEqual(fn("Anh Đinh"), "anh dinh", fn.__module__)

    def test_blueink_is_deliberately_not_wired(self):
        """Its fold is the stored double-send key on the Blue Ink Log tab.
        Changing it orphans every key already written, and the failure mode is a
        SECOND packet for somebody who already has one — which cannot be
        unsent. If this test fails, read automations/shared/names first."""
        from automations.blueink_docs import roster as BIR
        self.assertEqual(BIR._norm("Anh Đinh"), "anh đinh")


if __name__ == "__main__":
    unittest.main()
