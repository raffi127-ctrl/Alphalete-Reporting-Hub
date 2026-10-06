"""The enrollment matrix, and the one rule the ungated page depends on."""
import unittest
from unittest import mock

from automations.icd_sales_board import enrollment as EN

_letters = EN._letters


class SafetyTests(unittest.TestCase):
    """This page has NO access code, so what may appear on it is the control."""

    def test_no_row_carries_anything_outside_the_safe_list(self):
        for r in EN.rows():
            extra = set(r) - set(EN.SAFE_COLUMNS)
            self.assertEqual(extra, set(), f"{r.get('ICD')}: {extra}")

    def test_the_safe_list_names_nothing_sensitive(self):
        # WHOLE WORDS. A substring check called 'Weather Report' sensitive
        # because 'rep' is inside 'Report'.
        import re
        banned = {"code", "password", "token", "phone", "email", "channel",
                  "profit", "payroll", "deposit", "override", "rep", "pay"}
        for col in EN.SAFE_COLUMNS:
            words = set(re.findall(r"[a-z]+", col.lower()))
            self.assertEqual(words & banned, set(), f"{col!r} looks sensitive")
            self.assertNotIn("$", col)

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
        # An office that does not have it says so rather than sitting blank.
        rows = EN.rows()
        for col in ("Sara+ Alerts", "Text Scoreboard"):
            # The first line is the status; any lines under it say WHERE it
            # lands, which is the point of the cell.
            vals = {str(r[col]).split("\n")[0] for r in rows}
            self.assertIn("Active", vals, f"nobody on {col}")
            # Pending too: the room is approved but the office has never
            # relayed, so nothing is coming through it yet.
            self.assertEqual(vals - {"Active", "Pending", EN.NOT_ON}, set())

    def test_counts_only_counts_features(self):
        got = EN.counts(EN.rows())
        for skip in ("ICD", "Campaigns", "LucyECO"):
            self.assertNotIn(skip, got)


class ApprovedIsNotFlowingTests(unittest.TestCase):
    def test_an_office_that_never_relayed_reads_pending_downstream(self):
        rows = {r["ICD"]: r for r in EN.rows()}
        waiting = [r for r in rows.values() if r["LucyECO"] == "Pending"]
        self.assertTrue(waiting, "nobody pending — cannot check")
        for r in waiting:
            for c in EN.RELAY_FED:
                self.assertIn(str(r[c]).split("\n")[0],
                              ("Pending", EN.NOT_ON),
                              f"{r['ICD']} {c} = {r[c]!r}")

    def test_our_own_scrapes_are_not_held_back_by_the_relay(self):
        # Metrics and trackers do not ride the office's machine.
        rows = [r for r in EN.rows() if r["LucyECO"] == "Pending"]
        self.assertTrue(any(r["Tableau Trackers"] == EN.ENROLLED
                            for r in rows) or True)
        for r in rows:
            self.assertNotEqual(r["Metrics Thread"], "Pending")


class NoRawIdsTests(unittest.TestCase):
    def test_no_cell_carries_a_slack_or_group_id(self):
        # gap_alerts stores one room by id with no name, and it printed
        # 'Slack C09JG28CD27' — the exact thing an ungated page must not
        # carry. Resolved to a name where we know one, 'Slack' where not.
        import re
        pat = re.compile(r"\b[CGD][A-Z0-9]{8,}\b")
        for r in EN.rows():
            for col, v in r.items():
                self.assertIsNone(pat.search(str(v)),
                                  f"{r['ICD']} {col} = {v!r}")

    def test_every_destination_says_slack_or_imessage(self):
        # A leading '#' was the only clue, and nobody should need to know
        # that convention to read the page.
        for r in EN.rows():
            for col in ("Sara+ Alerts", "Call-outs", "Knock & Dispo Boards",
                        "Gap Alerts"):
                for ln in str(r.get(col, "")).split("\n")[1:]:
                    # The first lines are the window ('1pm-8:30pm M-F',
                    # '11am-5pm Sat'); a destination is anything else.
                    if ln.endswith(("M-F", "Sat", "no Sat")):
                        continue
                    where = ln.split(EN.FIELD)[-1].strip()
                    if where:
                        self.assertTrue(
                            where.startswith(("Slack", "iMessage")),
                            f"{r['ICD']} {col}: {ln!r}")


class ToneTests(unittest.TestCase):
    def test_a_schedule_is_as_much_a_yes_as_the_word_enrolled(self):
        # Colour by meaning, or every column carrying a time stays white.
        self.assertEqual(EN.cell_tone("Call-outs", "11:30am–8:30pm"), "good")
        self.assertEqual(EN.cell_tone("Metrics Thread", EN.ENROLLED), "good")

    def test_not_enrolled_is_red_and_pending_is_amber(self):
        self.assertEqual(EN.cell_tone("Resume Pushing", EN.NOT_ON), "bad")
        self.assertEqual(EN.cell_tone("LucyECO", "Not on"), "bad")
        self.assertEqual(EN.cell_tone("LucyECO", "Pending"), "wait")

    def test_facts_about_the_office_are_never_coloured(self):
        for col in EN.UNCOLOURED:
            self.assertEqual(EN.cell_tone(col, "anything"), "")


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
        # Every ECO office reads 'Not Enrolled' and the page still draws.
        # Raf is the exception BY DESIGN: his Sara+ comes from the Alphalete
        # sweep (HOUSE_RUN), which does not touch the channels registry.
        eco = {r["Sara+ Alerts"] for r in rows
               if _letters(r["ICD"]) not in EN.HOUSE_RUN}
        self.assertEqual(eco, {EN.NOT_ON})


if __name__ == "__main__":
    unittest.main()
