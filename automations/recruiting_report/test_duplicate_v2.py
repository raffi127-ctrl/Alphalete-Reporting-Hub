"""Raf's Duplicate % (Loom 2026-11-10): Cyrus Wade WE 11/8 = 103 / 462 = 22%."""
import unittest

from automations.recruiting_report import fetch_office, fill


class DuplicateV2(unittest.TestCase):
    def test_cyrus_example_from_loom(self):
        payload = {"processBox": 0, "reasons": [
            ["Ad Receipt", "31", 0], ["Duplicate/Already Interviewed", "103", 0],
            ["No Contact Info at All", "3", 0],
            ["Duplicate", "50", 1]]}            # Removed-from-Call-List box: ignored
        out = fetch_office._duplicate_metrics(payload, {"emails_received": 462})
        self.assertEqual(out, {"duplicates": 103, "total_applies_v2": 462, "duplicate_pct_v2": 22})

    def test_every_duplicate_reason_counts(self):
        payload = {"processBox": 0, "reasons": [
            ["Auto Process - Duplicate", "22", 0], ["Duplicate", "123", 0],
            ["Duplicate / Already Interviewed", "151", 0], ["AD Receipt", "111", 0]]}
        out = fetch_office._duplicate_metrics(payload, {"emails_received": 1417})
        self.assertEqual(out["duplicates"], 296)

    def test_no_box_writes_nothing(self):
        out = fetch_office._duplicate_metrics({"processBox": -1, "reasons": []}, {"emails_received": 10})
        self.assertIsNone(out["duplicates"])
        m = fill.apply_duplicate_v2({"removed_from_process_emails": 5, "total_applies": 9,
                                     "duplicate_pct": 50, "pull": 4, **out})
        self.assertNotIn("removed_from_process_emails", m)
        self.assertNotIn("duplicate_pct", m)
        self.assertEqual(m["pull"], 4)

    def test_swap(self):
        m = fill.apply_duplicate_v2({"removed_from_process_emails": 137, "total_applies": 444,
                                     "duplicate_pct": 45, "duplicates": 103,
                                     "total_applies_v2": 462, "duplicate_pct_v2": 22})
        self.assertEqual((m["removed_from_process_emails"], m["total_applies"], m["duplicate_pct"]),
                         (103, 462, 22))

    def test_new_label_still_matches_row(self):
        labels = [l.lower() for l in fill._all_labels(
            fill.OFFICE_METRIC_TO_ROW_LABEL["removed_from_process_emails"])]
        self.assertIn("duplicate/already interviewed", labels)
        self.assertIn("removed from process emails", labels)


if __name__ == "__main__":
    unittest.main()
