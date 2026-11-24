"""  python -m unittest automations.carlos_payroll_pull.test_person_check"""
import unittest

from automations.carlos_payroll_pull.person_check import person_rows

CSV = """Pay Period,11/09/2026 - 11/15/2026
Owner
First Name,Last Name,Gross Pay,Net Pay Addition,Net Pay Deduction,Comments
Ann,Boss,0,0,0,
Total,0
Sales Reps
First Name,Last Name,Gross Pay,Net Pay Addition,Net Pay Deduction,Comments
JANE,ALPHA BETA,450,100,0,"roadtrip, gas"
Janet,Other,10,0,0,
Total,460
Company Total,460
"""


class PersonRows(unittest.TestCase):
    def test_every_word_must_match(self):
        rows = person_rows(CSV, "jane alpha")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:9], ["11/09/2026", "11/15/2026", "Sales Reps", "JANE", "ALPHA BETA", "450", "100", "0",
                                       "roadtrip, gas"])

    def test_nobody(self):
        self.assertEqual(person_rows(CSV, "zed"), [])


if __name__ == "__main__":
    unittest.main()
