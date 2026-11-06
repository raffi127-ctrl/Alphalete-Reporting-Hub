"""One-letter last names get 'xxx' so the send goes (Megan 2026-11-06)."""
import unittest
from unittest import mock

from automations.oat_processing import run as R


class ShortLastName(unittest.TestCase):
    def test_padding_rule(self):
        self.assertEqual(R.padded_last_name("G"), "Gxxx")
        self.assertEqual(R.padded_last_name(" g. "), "gxxx")
        for keep in ("", "Go", "Garcia", "O'Neil", "1"):
            self.assertEqual(R.padded_last_name(keep), "", keep)

    def test_types_it_into_the_last_name_box(self):
        page = mock.MagicMock()
        loc = page.locator.return_value.first
        loc.count.return_value = 1
        a = R.Applicant(first_name="Alianna", last_name="G")
        self.assertTrue(R._pad_short_last_name(page, a, live=True))
        page.locator.assert_called_with("input[name='lname']")
        loc.press_sequentially.assert_called_once_with("Gxxx", delay=35)
        self.assertEqual(a.last_name, "Gxxx")

    def test_normal_name_untouched(self):
        page = mock.MagicMock()
        a = R.Applicant(first_name="Ana", last_name="Garcia")
        self.assertFalse(R._pad_short_last_name(page, a, live=True))
        page.locator.assert_not_called()

    def test_dry_run_never_types(self):
        page = mock.MagicMock()
        a = R.Applicant(first_name="Lili", last_name="G")
        self.assertFalse(R._pad_short_last_name(page, a, live=False))
        page.locator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
