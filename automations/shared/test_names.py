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


# ------------------------------------- the helpers that have to be able to SHIP

def test_the_whole_name_helpers_import_nothing_an_office_mac_lacks():
    """norm_name and base_name moved here on 2026-11-11 so apex_new_starts can
    use them on an OFFICE computer. They lived in terminated_reps.board, which
    reaches recruiting_report.fill (Google Sheets) at import time -- an office
    Mac has no Google access, so importing it there was a crash, and a helper
    that cannot travel is one somebody rewrites slightly differently."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "automations" / "shared" / "names.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            reached.add(node.module.split(".")[0])
    assert not (reached & {"automations"}), \
        "this module must not reach into automations at all: %s" % sorted(reached)


def test_base_name_still_recognises_the_same_person_across_week_tabs():
    from automations.shared.names import base_name
    assert base_name("Jaylen (Ash) Walker (Wk 3)") == base_name("Jaylen (Ash) Walker")


def test_terminated_reps_still_exports_them_for_its_own_callers():
    """Moved, not taken away."""
    from automations.shared import names as N
    from automations.terminated_reps import board as TB
    assert TB.base_name is N.base_name and TB.norm_name is N.norm_name


def test_the_week_and_calendar_helpers_can_ship_too():
    """Same rule, same day, same reason: office_admin.fdot runs on an office
    computer and needed week_start_of (from icd_onboarding.board, whose
    siblings read Sheets) and the calendar-nav script (from raf_daily_update,
    which is Alphalete's own)."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "automations"
    for rel in ("shared/onboarding_week.py", "office_admin/cal_nav.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        reached = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                reached |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                reached.add(node.module.split(".")[0])
        assert "automations" not in reached, "%s reaches %s" % (rel, sorted(reached))


def test_the_board_and_raf_daily_still_export_what_they_always_did():
    import datetime as dt
    from automations.icd_onboarding import board as B
    from automations.office_admin.cal_nav import CAL_NAV_JS
    from automations.raf_daily_update.run import _CAL_NAV_JS
    from automations.shared.onboarding_week import week_start_of
    assert B.week_start_of is week_start_of and B.monday_of is week_start_of
    assert _CAL_NAV_JS == CAL_NAV_JS, "one copy, not two"
    # and the Sunday rule itself is unchanged
    assert B.week_start_of(dt.date(2026, 11, 11)) == dt.date(2026, 11, 8)
    assert B.week_start_of(dt.date(2026, 11, 8)) == dt.date(2026, 11, 8)
    assert B.week_start_of(dt.date(2026, 11, 14)) == dt.date(2026, 11, 8)
