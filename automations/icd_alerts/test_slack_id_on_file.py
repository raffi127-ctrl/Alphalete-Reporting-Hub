"""A sign-up row with no Slack id falls back to resources/owner-slack-ids.md.

Megan 2026-11-10: Samuel's "computer has gone quiet" notice reached her and Eve
but not Samuel -- "No Slack id on file" -- because nobody had filled the
column on his sign-up row. Made-up ids throughout.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import offices as O

MD = """\
| Owner | Office | Slack ID | Notes |
|---|---|---|---|
| Pat Example | Example Office | U0AAAAAAAA1 | look-alike U0BBBBBBBB2 is a second account |
| Sam "Sammy" Sample (owner) | Sample Office | U0CCCCCCCC3 | |
| Two Accounts | Somewhere | not confirmed | U0DDDDDDDD4 or U0EEEEEEEE5 |
"""


class SlackIdOnFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.md = Path(self.dir.name) / "ids.md"
        self.md.write_text(MD, encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_finds_the_owner_by_first_and_last_name(self):
        self.assertEqual(O.slack_id_on_file("pat example", self.md), "U0AAAAAAAA1")
        self.assertEqual(O.slack_id_on_file("Sam Sample", self.md), "U0CCCCCCCC3")

    def test_never_takes_an_id_out_of_the_notes(self):
        self.assertEqual(O.slack_id_on_file("Two Accounts", self.md), "")

    def test_unknown_owner_or_missing_file_is_blank(self):
        self.assertEqual(O.slack_id_on_file("Nobody Here", self.md), "")
        self.assertEqual(O.slack_id_on_file("Pat", self.md), "")
        self.assertEqual(O.slack_id_on_file("Pat Example", Path("/nonexistent.md")), "")

    def test_a_blank_cell_on_the_sign_up_row_uses_the_file(self):
        row = {"office_key": "pat", "owner": "Pat Example", "status": "pending"}
        with mock.patch.object(O, "_SLACK_IDS_MD", self.md):
            self.assertEqual(O._office_from_signup(row).slack_user_id, "U0AAAAAAAA1")

    def test_the_sheet_cell_wins_over_the_file(self):
        row = {"office_key": "pat", "owner": "Pat Example", "status": "pending",
               "slack_user_id": "U0ZZZZZZZZ9"}
        with mock.patch.object(O, "_SLACK_IDS_MD", self.md):
            self.assertEqual(O._office_from_signup(row).slack_user_id, "U0ZZZZZZZZ9")


if __name__ == "__main__":
    unittest.main()
