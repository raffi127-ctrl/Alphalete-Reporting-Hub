"""A Slack channel ID box must refuse anything that can't be a channel ID.

The bug this pins: Joe typed his workspace handle "loganlegacygroup" into the
Channel ID box on both sign-up forms (2026-09-11). Nothing objected, both
requests saved, and the only symptom was Lucy's membership check failing on the
Slack ping — long after he'd left the form.
"""
import unittest

from automations.shared.onboarding_ui import normalize_channel_id as norm


class Accepts(unittest.TestCase):
    def test_a_real_id(self):
        self.assertEqual(norm("C0ABC12DE"), ("C0ABC12DE", ""))

    def test_a_private_or_dm_id(self):
        for got in ("G01ABC23DEF", "D08XY9Z12"):
            self.assertEqual(norm(got), (got, ""))

    def test_it_shouts_a_lowercase_id_back_uppercase(self):
        self.assertEqual(norm("c0abc12de"), ("C0ABC12DE", ""))

    def test_surrounding_whitespace(self):
        self.assertEqual(norm("  C0ABC12DE \n"), ("C0ABC12DE", ""))

    def test_a_pasted_copy_link(self):
        """What 'Copy link' actually puts on the clipboard."""
        got, why = norm("https://alphalete.slack.com/archives/C08ABC123XY/p1757")
        self.assertEqual((got, why), ("C08ABC123XY", ""))

    def test_a_pasted_address_bar_url(self):
        got, why = norm("https://app.slack.com/client/T01TEAM99/C08ABC123XY")
        self.assertEqual((got, why), ("C08ABC123XY", ""))

    def test_slacks_own_mention_markup(self):
        self.assertEqual(norm("<#C0ABC12DE|office-sales>"), ("C0ABC12DE", ""))


class Refuses(unittest.TestCase):
    def _why(self, got):
        clean, why = norm(got)
        self.assertEqual(clean, "", "{!r} should not be accepted".format(got))
        self.assertTrue(why, "a refusal must say what to do")
        return why

    def test_the_workspace_handle_joe_typed(self):
        why = self._why("loganlegacygroup")
        self.assertIn("C0ABC12DE", why)          # shows what one looks like
        self.assertIn("Channel ID", why)         # and where to find it

    def test_a_channel_name(self):
        self._why("#joseph-logan-office")
        self._why("joseph-logan-office")

    def test_a_word_that_happens_to_start_with_c(self):
        self._why("cancels")
        self._why("Corporate")

    def test_too_short_to_be_an_id(self):
        self._why("C0AB")

    def test_an_email_or_url_with_no_id_in_it(self):
        self._why("joseph@loganlegacygroup.com")
        self._why("https://loganlegacygroup.com")


class Blank(unittest.TestCase):
    def test_blank_is_not_this_checks_problem(self):
        """The required-field check owns "you left it empty" — this one staying
        quiet is what keeps a fresh form from opening covered in red."""
        for got in ("", "   ", None):
            self.assertEqual(norm(got), ("", ""))


if __name__ == "__main__":
    unittest.main()
