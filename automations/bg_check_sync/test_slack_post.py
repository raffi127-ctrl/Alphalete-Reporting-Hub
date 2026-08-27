"""The weekly thread's sections — chiefly the one that says a row is claiming
something Sterling can't back."""
from __future__ import annotations

import unittest

from automations.bg_check_sync import slack_post


class UnbackedSectionTests(unittest.TestCase):

    PEOPLE = [("Cindy Flores", "Passed"), ("Ana Diaz", "Passed")]

    def test_a_row_with_no_check_behind_it_is_called_out(self):
        body = slack_post.render("9/7/2026", self.PEOPLE, [], "Aug 26, 9:00 PM",
                                 unbacked=[("Cindy Flores", "Passed")])
        self.assertIn("Someone marked these on the OBCL", body)
        self.assertIn("no Sterling email says so", body)
        self.assertIn("Cindy Flores — marked Passed", body)

    def test_they_still_appear_in_their_own_bucket(self):
        """The section is a warning, not a reclassification — her row does say
        Passed, and the thread should keep showing what the sheet says."""
        body = slack_post.render("9/7/2026", self.PEOPLE, [], "Aug 26, 9:00 PM",
                                 unbacked=[("Cindy Flores", "Passed")])
        passed = body.split("*✅ Passed")[1]
        self.assertIn("Cindy Flores", passed.split("⚠️")[0])

    def test_nothing_unbacked_means_no_section(self):
        body = slack_post.render("9/7/2026", self.PEOPLE, [], "Aug 26, 9:00 PM",
                                 unbacked=[])
        self.assertNotIn("Someone marked these", body)

    def test_the_argument_is_optional(self):
        """Callers that predate it must not break."""
        body = slack_post.render("9/7/2026", self.PEOPLE, [], "Aug 26, 9:00 PM")
        self.assertNotIn("Someone marked these", body)


if __name__ == "__main__":
    unittest.main()
