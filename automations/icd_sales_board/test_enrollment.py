"""The enrollment matrix, and the one rule the ungated page depends on."""
import unittest
from unittest import mock

from automations.icd_sales_board import enrollment as EN


class SafetyTests(unittest.TestCase):
    """This page has NO access code, so what may appear on it is the control."""

    def test_no_row_carries_anything_outside_the_safe_list(self):
        for r in EN.rows():
            extra = set(r) - set(EN.SAFE_COLUMNS)
            self.assertEqual(extra, set(), f"{r.get('ICD')}: {extra}")

    def test_the_safe_list_names_nothing_sensitive(self):
        banned = ("code", "password", "token", "phone", "email", "channel",
                  "$", "profit", "payroll", "deposit", "override", "rep")
        for col in EN.SAFE_COLUMNS:
            for b in banned:
                self.assertNotIn(b, col.lower(), f"{col!r} looks sensitive")

    def test_the_rollout_list_no_longer_prints_board_codes(self):
        # It used to, while it was admin-only. This page makes that unsafe.
        from automations.icd_sales_board import rollout as RO
        src = __import__("inspect").getsource(RO.status_rows)
        self.assertNotIn("Board code", src)


class JoinTests(unittest.TestCase):
    def test_a_short_registry_key_matches_the_full_name(self):
        # gap_alerts calls Raf's office 'rafael'; the board calls him
        # 'Rafael Hidalgo'. An exact join read zero for everyone.
        self.assertEqual(EN._letters("Rafael Hidalgo"), "rafaelhidalgo")
        self.assertTrue("rafaelhidalgo".startswith(EN._letters("rafael")))

    def test_a_scheduled_feature_shows_when_not_a_tick(self):
        rows = EN.rows()
        cells = [r["Knock & Dispo Boards"] for r in rows
                 if r["Knock & Dispo Boards"]]
        self.assertTrue(cells, "nobody enrolled — cannot check the shape")
        for c in cells:
            self.assertNotIn(c.lower(), ("yes", "true", "x"))

    def test_the_round_the_clock_ones_just_say_active(self):
        # Noon to midnight plus a 2am catch-up is near enough 24/7 that the
        # window was noise in a column people scan for "do they have it?".
        rows = EN.rows()
        for col in ("Sara+ Alerts", "Text Scoreboard"):
            on = [r[col] for r in rows if r[col]]
            self.assertTrue(on, f"nobody on {col}")
            self.assertEqual(set(on), {"Active"})

    def test_counts_only_counts_features(self):
        got = EN.counts(EN.rows())
        for skip in ("ICD", "Campaigns", "LucyECO"):
            self.assertNotIn(skip, got)


class EcoStateTests(unittest.TestCase):
    def test_the_five_rollout_states_fold_into_four_words(self):
        from automations.icd_sales_board import rollout as RO
        self.assertEqual(EN.eco_state(RO.LIVE), "Active")
        self.assertEqual(EN.eco_state(RO.UPDATE), "Partial")
        self.assertEqual(EN.eco_state(RO.QUIET), "Partial")
        self.assertEqual(EN.eco_state(RO.WAITING), "Pending")
        self.assertEqual(EN.eco_state(RO.NONE), "Not on")

    def test_every_rollout_status_is_mapped(self):
        # A state nobody mapped would silently read 'Not on', which is the
        # one answer that is actively wrong for an enrolled office.
        from automations.icd_sales_board import rollout as RO
        for s in RO.ORDER:
            self.assertIn(s, EN.ECO_STATE, f"{s!r} has no public wording")

    def test_the_page_only_ever_shows_those_four(self):
        allowed = {"Active", "Partial", "Pending", "Not on"}
        self.assertTrue(set(r["LucyECO"] for r in EN.rows()) <= allowed)


class ResilienceTests(unittest.TestCase):
    def test_an_unreadable_registry_blanks_a_column_not_the_page(self):
        with mock.patch.object(EN, "_channels", return_value={}):
            rows = EN.rows()
        self.assertTrue(rows)
        self.assertEqual([r for r in rows if r["Sara+ Alerts"]], [])


if __name__ == "__main__":
    unittest.main()
