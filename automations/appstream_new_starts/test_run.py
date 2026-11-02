import datetime as dt
import unittest

from automations.appstream_new_starts.run import to_rows


class ToRows(unittest.TestCase):
    def test_known_columns_by_header_plus_extras(self):
        hdr = ["First Name", "Last Name", "Email", "Phone", "Interviewer"]
        rows = [["Ana", "Lopez", "a@x.com", "2145550100", "Nick"],
                ["Bo", "Diaz", "", "", ""]]
        out = to_rows("Total New Starts Scheduled", dt.date(2026, 11, 6), hdr, rows)
        self.assertEqual(out[0], ["Total New Starts Scheduled", "2026-11-06",
                                  "Ana Lopez", "2145550100", "a@x.com",
                                  "interviewer=Nick"])
        self.assertEqual(out[1][2:5], ["Bo Diaz", "", ""])

    def test_missing_columns_do_not_crash(self):
        out = to_rows("New Starts Showed Up", dt.date(2026, 11, 6),
                      ["Name"], [["Ana Lopez"]])
        self.assertEqual(out[0][2], "")
        self.assertIn("name=Ana Lopez", out[0])


if __name__ == "__main__":
    unittest.main()
