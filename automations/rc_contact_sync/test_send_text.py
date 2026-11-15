import unittest

from automations.rc_contact_sync import send_text as S

BOOK = [{"firstName": "John", "lastName": "Coward", "mobilePhone": "+12147739399"},
        {"firstName": "John", "lastName": "Coward - Line 2", "mobilePhone": "+19722225000"},
        {"firstName": "JOHN", "lastName": "COWARD", "mobilePhone": "+12147739399"},
        {"firstName": "John", "lastName": "Smith", "mobilePhone": "+12145550000"}]


class Pick(unittest.TestCase):
    def test_main_contact_not_the_line_contacts(self):
        found = S.main_contacts(BOOK, ["John", "Coward"])
        self.assertEqual(list(found), ["John Coward"])          # the two spellings are one person
        self.assertEqual(len(found["John Coward"]), 1)
        self.assertTrue(S.pick_number(found).endswith("2147739399"))

    def test_ambiguous_or_missing_sends_nothing(self):
        self.assertIsNone(S.pick_number(S.main_contacts(BOOK, ["John"])))      # Coward and Smith
        self.assertIsNone(S.pick_number(S.main_contacts(BOOK, ["Nobody"])))


if __name__ == "__main__":
    unittest.main()
