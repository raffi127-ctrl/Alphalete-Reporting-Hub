# -*- coding: utf-8 -*-
"""The grade card's arithmetic, and the two ways it has already been wrong.

Run: python -m unittest automations.sms_audit.test_gradecard
"""
import unittest

from automations.sms_audit import gradecard as GC


class Bands(unittest.TestCase):
    def test_higher_is_better(self):
        self.assertEqual(GC._band(85, 80, 70, 60), "A")
        self.assertEqual(GC._band(80, 80, 70, 60), "A")   # on the cut-off
        self.assertEqual(GC._band(64, 80, 70, 60), "C")
        self.assertEqual(GC._band(45, 80, 70, 60), "D")
        self.assertEqual(GC._band(10, 80, 70, 60), "F")

    def test_lower_is_better(self):
        self.assertEqual(GC._band(0, 0, 3, 10, higher_is_better=False), "A")
        self.assertEqual(GC._band(12, 0, 3, 10, higher_is_better=False), "D")
        self.assertEqual(GC._band(99, 0, 3, 10, higher_is_better=False), "F")

    def test_no_value_is_no_grade(self):
        self.assertIsNone(GC._band(None, 1, 2, 3))


class ShowRate(unittest.TestCase):
    """retention.load returns (week, date, booker, shown).

    It used to be documented as a 3-tuple, and reading r[2] picked up the
    BOOKER'S NAME — always truthy — which graded every office 100% and hid a
    real 48%. The flag is found by type now, so a new column cannot do it
    again."""

    def test_finds_the_flag_whatever_its_position(self):
        rows = [("w0821", "08-17-2026", "A. Messaging", True),
                ("w0821", "08-17-2026", "A. Messaging", False),
                ("w0821", "08-18-2026", "J. Pena", False),
                ("w0821", "08-18-2026", "J. Pena", False)]
        item, skip = GC._show_rate(rows)
        self.assertIsNone(skip)
        self.assertIn("25%", item["number"])

    def test_three_field_shape_still_works(self):
        rows = [("w0821", "A. Messaging", True),
                ("w0821", "A. Messaging", False)]
        item, _ = GC._show_rate(rows)
        self.assertIn("50%", item["number"])

    def test_dict_records_score_off_the_status(self):
        rows = [{"status": "Interview Completed"}, {"status": "No Show"},
                {"status": "Brought on Board"}, {"status": "No Show"}]
        item, _ = GC._show_rate(rows)
        self.assertIn("50%", item["number"])

    def test_no_flag_is_not_measured_rather_than_a_pass(self):
        item, skip = GC._show_rate([("w0821", "A. Messaging")])
        self.assertIsNone(item)
        self.assertIsNotNone(skip)

    def test_nothing_pulled_is_not_measured(self):
        item, skip = GC._show_rate([])
        self.assertIsNone(item)
        self.assertIn("no bookings pulled", skip[1])


class NotPulled(unittest.TestCase):
    """A page nobody pulled is missing data, never a fault and never a pass."""

    def test_settings_not_pulled_is_skipped_once(self):
        """One line about the page, not one per field on it."""
        got, skipped = GC._settings(
            {"settings": [("NOT PULLED", "office 11280")],
             "escalations": [("NOT PULLED", "office 11280")],
             "window": None})
        self.assertEqual([i for i in got if i["area"] == "AI settings"], [])
        areas = [a for a, _why in skipped]
        self.assertIn("AI settings", areas)
        self.assertIn("What the AI replies to applicants", areas)
        self.assertNotIn("Time to accept a slot", areas)

    def test_window_missing_from_a_page_we_did_pull_is_its_own_line(self):
        _got, skipped = GC._settings(
            {"settings": [("OK", "")], "escalations": [], "window": None})
        self.assertIn("Time to accept a slot", [a for a, _why in skipped])

    def test_a_real_setting_fault_is_reported(self):
        got, _ = GC._settings(
            {"settings": [("BAD", "AI name matches the escalation contact")],
             "escalations": [], "window": 55})
        self.assertTrue(any(i["area"] == "AI settings" for i in got))

    def test_window_is_graded(self):
        got, _ = GC._settings({"settings": [], "escalations": [], "window": 5})
        win = [i for i in got if i["area"] == "Time to accept a slot"][0]
        self.assertEqual(win["grade"], "F")


class Build(unittest.TestCase):
    def test_passing_areas_are_kept_apart_from_the_misses(self):
        card = GC.build({"office": "11280"},
                        conv={"ok": True, "rate": 95.0, "booked": 95,
                              "applied": 100},
                        rows=[("w", "d", "b", False)] * 10)
        self.assertTrue(any(i["area"] == "Call list retention"
                            for i in card["holding"]))
        self.assertTrue(any(i["area"] == "Showed up" for i in card["items"]))

    def test_misses_are_ranked_worst_first(self):
        card = GC.build({"office": "x"},
                        conv={"ok": True, "rate": 20.0, "booked": 2,
                              "applied": 10},
                        msgs={"errors": ["a"], "dodged": {}, "people": 100,
                              "delivery": {}})
        self.assertEqual(card["items"][0]["area"], "Call list retention")

    def test_a_skipped_check_blocks_a_clean_A(self):
        card = GC.build({"office": "x"}, gaps=["interview address"])
        self.assertEqual(card["overall"], "B")
        self.assertEqual(card["items"], [])


if __name__ == "__main__":
    unittest.main()


class NoGradelessItems(unittest.TestCase):
    """An item with no grade is missing data, not a finding.

    `_band` returns None when it is handed None, and one unguarded branch
    let that reach the sort, where "ABCDF".index(None) killed the run."""

    def test_settings_with_no_window_yields_no_gradeless_item(self):
        got, _ = GC._settings(
            {"settings": [("NOT PULLED", "x")], "escalations": [],
             "window": None})
        self.assertTrue(all(i["grade"] in "ABCDF" for i in got))

    def test_build_drops_a_gradeless_item(self):
        card = GC.build(
            {"office": "x"},
            ai={"settings": [("NOT PULLED", "x")], "escalations": [],
                "window": None})
        for i in card["items"] + card["holding"]:
            self.assertIn(i["grade"], "ABCDF")


class TypingVersusHouseRules(unittest.TestCase):
    """Two different faults, two different fixes.

    Megan 2026-10-06 asked "what is house rules in texts?" — and it was
    not house rules. The row was counting text_errors (grammar, spelling)
    under a house-rules label, and the real breaches (wrong address, no
    suite, "base" pay) were not on the card at all."""

    MSGS = {
        "people": 100,
        "errors": [{"kind": "grammar"}, {"kind": "spelling"}],
        "dodged": [],
        "delivery": {},
        "coaching": [{"issue": "Sent the wrong office address", "count": 3},
                     {"issue": "Left the suite off the address", "count": 3},
                     {"issue": "Told applicants there is a base pay",
                      "count": 1}],
    }

    def _areas(self):
        got, _ = GC._messages(self.MSGS)
        return {i["area"]: i for i in got}

    def test_typing_counts_the_typos_not_the_house_rules(self):
        self.assertIn("2 messages", self._areas()["Typing and grammar mistakes"]["number"])

    def test_house_rules_counts_the_breaches_not_the_typos(self):
        self.assertIn("7 texts", self._areas()["House rules broken"]["number"])

    def test_house_rules_names_the_worst_one(self):
        self.assertIn("wrong office address",
                      self._areas()["House rules broken"]["action"])

    def test_typing_says_coach_not_edit_a_template(self):
        self.assertIn("Coach", self._areas()["Typing and grammar mistakes"]["action"])

    def test_no_coaching_still_reports_the_row_as_clean(self):
        msgs = dict(self.MSGS, coaching=[])
        got, _ = GC._messages(msgs)
        row = [i for i in got if i["area"] == "House rules broken"][0]
        self.assertEqual(row["grade"], "A")
