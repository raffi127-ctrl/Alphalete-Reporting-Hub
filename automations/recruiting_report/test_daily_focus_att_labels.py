"""Daily Focus tabs in the ATT Program wording still find every metric row."""
import unittest

from automations.recruiting_report import daily_focus as df

OLD = ["Sent to Call list - Apps / Pull", "Removed from process Emails",
       "Total Applies", "Duplicate % ", "Retention to Call list",
       "1st rds showed up", "1st rds scheduled", "1st rd retention",
       "% of 1st rds Booked for 2nd", "2nd rds showed up", "2nd rds scheduled",
       "2nd rd retention", "Job Offered", "BOB", "Job Offered Retention",
       "BOB %", "New Starts Showed ", "New Starts Scheduled ",
       "New Start Retention "]
NEW = ["APPS / PULL", "Duplicate/Already Interviewed", "Total Applies",
       "Duplicate %", "Retention to Call list", "1ST BOOKED", "1ST SHOWED",
       "1st Retention", "Retention 1st showed Booked for 2nd", "2ND BOOKED",
       "2ND SHOWED", "2ND Retention", "Job Offered", "BOB",
       "Job Offered Retention", "BOB Conversion", "New Starts Scheduled",
       "New Starts Showed", "New Start Retention"]


def _rows(labels):
    # anchor = row 1; metrics start at row 5 (METRICS_START_OFFSET = 4)
    col3 = ["Current Week", "", "Office Focus Report", ""] + labels
    return df._find_metric_rows_in_section(col3, 1)


class AttLabels(unittest.TestCase):
    def test_both_layouts_find_all_19_metrics(self):
        old, new = _rows(OLD), _rows(NEW)
        self.assertEqual(len(old), 19)
        self.assertEqual(set(old), set(new))

    def test_new_layout_rows_point_at_the_right_label(self):
        r = _rows(NEW)
        self.assertEqual(r["first_booked"], 10)
        self.assertEqual(r["first_showed"], 11)
        self.assertEqual(r["second_booked"], 14)
        self.assertEqual(r["second_showed"], 15)
        self.assertEqual(r["bob"], 18)
        self.assertEqual(r["pct_bob_conversion"], 20)
        self.assertEqual(r["new_starts_scheduled"], 21)
        self.assertEqual(r["new_starts_showed"], 22)
        self.assertEqual(r["removed_from_process_emails"], 6)


if __name__ == "__main__":
    unittest.main()
