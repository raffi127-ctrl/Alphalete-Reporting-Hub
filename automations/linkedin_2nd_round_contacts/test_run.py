"""python -m unittest automations.linkedin_2nd_round_contacts.test_run"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.applicant_contacts import contacts as K
from automations.linkedin_2nd_round_contacts import run as R


class RunTest(unittest.TestCase):
    def test_header_has_no_zero_pad(self):
        self.assertEqual(R.date_header(dt.date(2026, 10, 7)), "Oct 7, 2026")

    def test_days_sunday_to_today(self):
        wed = dt.date(2026, 10, 28)
        days = R.days_to_read(wed)
        self.assertEqual(days[0], dt.date(2026, 10, 25))
        self.assertEqual(days[-1], wed)

    def test_sunday_also_reads_saturday(self):
        sun = dt.date(2026, 11, 1)
        self.assertEqual(R.days_to_read(sun),
                         [dt.date(2026, 10, 31), sun])

    HEADER = ["", "first name", "last name", "email", "phone", "rating"]

    def test_rows_to_applicants_by_header(self):
        rows = [["1", "JUAN", "perez", "J@X.COM", "(214) 555-0101", "5"]]
        self.assertEqual(R.to_applicants(self.HEADER, rows), [
            {"first_name": "Juan", "last_name": "Perez",
             "email": "j@x.com", "phone": "2145550101"}])

    def test_moved_column_still_found(self):
        header = ["", "phone", "first name", "last name", "email"]
        rows = [["1", "214-555-0101", "Ana", "Diaz", "a@x.com"]]
        self.assertEqual(R.to_applicants(header, rows)[0]["phone"],
                         "2145550101")

    def test_missing_column_is_loud(self):
        with self.assertRaises(RuntimeError):
            R.to_applicants(["", "first name", "last name", "email"], [])

    def test_count_from_href(self):
        self.assertEqual(R._count("index.cfm?p=715&count=3&dt=1"), 3)
        self.assertEqual(R._count("index.cfm?p=715&count=0&dt=1"), 0)
        self.assertEqual(R._count(None), 0)

    def test_note_lands_in_contact(self):
        body = K.person_body({"first_name": "Juan", "phone": "2145550101"},
                             "", dt.date(2026, 10, 28), R.NOTE)
        self.assertEqual(body["biographies"][0]["value"],
                         R.NOTE + ", 10/28/2026")

    def test_default_note_unchanged(self):
        body = K.person_body({"first_name": "Juan"}, "Raf",
                             dt.date(2026, 10, 28))
        self.assertEqual(body["biographies"][0]["value"],
                         "Applicant - added from Slack by Raf, 10/28/2026")


if __name__ == "__main__":
    unittest.main()
