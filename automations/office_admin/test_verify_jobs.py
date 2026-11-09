"""The second reader's matching rule: only people found on the ICD's own
ApplicantStream list are ever sent (verify_jobs.match). Offline."""
import unittest

from automations.office_admin.verify_jobs import match


class MatchTest(unittest.TestCase):
    def test_email_match_ignores_case(self):
        kept, dropped = match([{"first_name": "Ann", "last_name": "Lee", "email": "Ann@X.com"}],
                              [{"first_name": "Ann", "last_name": "Lee", "email": "ann@x.com"}], "account 1")
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_someone_not_on_the_list_is_dropped_and_named(self):
        kept, dropped = match([{"first_name": "Bob", "last_name": "Ray", "email": "bob@x.com"}],
                              [{"first_name": "Ann", "last_name": "Lee", "email": "ann@x.com"}], "account 11280")
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["name"], "Bob Ray")
        self.assertIn("11280", dropped[0]["why"])

    def test_same_name_different_email_is_dropped(self):
        # A list row WITH an email only matches by email -- a namesake on
        # another account's list must never pass on the name alone.
        kept, _ = match([{"first_name": "Ann", "last_name": "Lee", "email": "other@x.com"}],
                        [{"first_name": "Ann", "last_name": "Lee", "email": "ann@x.com"}], "account 1")
        self.assertEqual(kept, [])

    def test_name_match_when_the_list_has_no_email(self):
        kept, _ = match([{"first_name": "Cy", "last_name": "Tan", "email": "cy@x.com"}],
                        [{"first_name": "Cy", "last_name": "Tan", "email": ""}], "account 1")
        self.assertEqual(len(kept), 1)

    def test_empty_list_sends_nobody(self):
        kept, dropped = match([{"first_name": "Ann", "last_name": "Lee", "email": "a@x.com"}], [], "account 1")
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)


if __name__ == "__main__":
    unittest.main()
