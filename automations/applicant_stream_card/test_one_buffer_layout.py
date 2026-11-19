"""AppStream's 11/16 AI Settings layout: one buffer, plus a prep time. Offline.

Between 12:51 and 15:44 CT on 11/16 the two timeslot buffers on p=1504 became
one field, "Earliest interview time the AI can offer (minutes from now)", and
"Interviewer prep time (in minutes)" appeared. 11580's page on 11/18:
earliest 15, prep 5, ghosting 60, no "accepted" field at all.
"""
from __future__ import annotations

import unittest

from automations.applicant_stream_card import changes as C
from automations.applicant_stream_card import fixes as F
from automations.applicant_stream_card import setup_page as P
from automations.sms_audit import ai_settings as AIS
from automations.sms_audit import pull_ai_settings as PULL

NEW = {"offered_buffer": "15", "ghosting_threshold": "60",
       "interviewer_prep_buffer": "5"}
OLD = {"offered_buffer": "60", "accepted_buffer": "60",
       "ghosting_threshold": "60"}


class ReaderTest(unittest.TestCase):
    def test_new_labels_map_to_the_keys_the_audit_reads(self):
        self.assertEqual(
            PULL.FIELDS["earliest interview time the ai can offer minutes from now"],
            "offered_buffer")
        self.assertEqual(PULL.FIELDS["interviewer prep time in minutes"],
                         "interviewer_prep_buffer")
        self.assertNotIn("interviewer_prep_buffer", PULL.INFO_KEYS)

    def test_no_accepted_field_is_not_a_hole_any_more(self):
        holes = PULL.office_holes({}, NEW, [{"name": "x"}])
        self.assertFalse([h for h in holes if "buffer" in h], holes)

    def test_a_missing_earliest_offer_still_is(self):
        holes = PULL.office_holes({}, {"ghosting_threshold": "60"}, [{"name": "x"}])
        self.assertTrue([h for h in holes if "offered_buffer" in h], holes)

    def test_old_layout_with_accepted_left_empty_is_still_a_hole(self):
        holes = PULL.office_holes({}, {"offered_buffer": "60"}, [{"name": "x"}],
                                  blank={"accepted_buffer"})
        self.assertTrue([h for h in holes if "accepted_buffer" in h], holes)


class IcdAuditTest(unittest.TestCase):
    def test_one_field_is_not_window_too_short(self):
        kinds = [k for k, _ in AIS.lint({"ai_assistant_name": "Ava"}, NEW,
                                        median_reply=26)]
        self.assertNotIn("WINDOW TOO SHORT", kinds)

    def test_no_earliest_offer_is(self):
        kinds = [k for k, _ in AIS.lint({"ai_assistant_name": "Ava"},
                                        {"ghosting_threshold": "60"})]
        self.assertIn("WINDOW TOO SHORT", kinds)


class CardTest(unittest.TestCase):
    def test_earliest_offer_15_is_flagged_too_soon_under_its_new_name(self):
        items = F.check_preferences(NEW)
        self.assertEqual([i["kind"] for i in items], ["PREF offered_buffer"])
        self.assertEqual(items[0]["title"], F.TOO_SOON_WHY[0])
        self.assertIn("Earliest Interview Time", F.STANDARD_LABEL["offered_buffer"])

    def test_setup_page_rows_for_the_new_layout(self):
        setup = P.gather({"office_name": "Alphalete"}, NEW, None)
        labels = [r[0] for r in setup["prefs"]]
        self.assertEqual(labels, ["Earliest time the AI suggests", "Ghosting flag",
                                  "Interviewer prep time"])
        rows = {r[0]: r for r in setup["prefs"]}
        self.assertTrue(rows["Earliest time the AI suggests"][4])   # 15 < 30
        self.assertIsNone(rows["Interviewer prep time"][2])         # no standard
        self.assertIsNone(rows["Interviewer prep time"][4])         # not graded

    def test_old_layout_rows_unchanged(self):
        setup = P.gather({"office_name": "Alphalete"}, OLD, None)
        self.assertEqual([r[0] for r in setup["prefs"]],
                         ["Earliest time the AI suggests",
                          "Earliest time an applicant can ask for", "Ghosting flag"])

    def test_change_log_names_rows_by_their_own_label(self):
        snap = C.snapshot(P.gather({"office_name": "Alphalete"}, NEW, None))
        self.assertEqual(snap["Buffer · Ghosting flag"], "60")
        self.assertEqual(snap["Buffer · Interviewer prep time"], "5")
        self.assertNotIn("Buffer · Earliest time an applicant can ask for", snap)


if __name__ == "__main__":
    unittest.main()
