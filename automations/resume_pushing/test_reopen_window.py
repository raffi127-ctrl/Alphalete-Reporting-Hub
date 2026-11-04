"""A windowless Chrome gets a window before connect_over_cdp (Lucy 4, 11/3)."""
import unittest
from unittest import mock

from automations.resume_pushing import run as R


class ReopenWindow(unittest.TestCase):
    def test_opens_when_no_window(self):
        counts = iter([0, 1])
        with mock.patch.object(R, "_cdp_page_count", lambda port=None: next(counts)), \
             mock.patch("urllib.request.urlopen") as uo:
            self.assertTrue(R._reopen_window_if_none("9999"))
            req = uo.call_args[0][0]
            self.assertEqual(req.get_method(), "PUT")
            self.assertIn("127.0.0.1:9999/json/new", req.full_url)

    def test_leaves_open_window_alone(self):
        with mock.patch.object(R, "_cdp_page_count", lambda port=None: 2), \
             mock.patch("urllib.request.urlopen") as uo:
            self.assertFalse(R._reopen_window_if_none("9999"))
            uo.assert_not_called()

    def test_unreachable_chrome_does_nothing(self):
        with mock.patch.object(R, "_cdp_page_count", lambda port=None: -1), \
             mock.patch("urllib.request.urlopen") as uo:
            self.assertFalse(R._reopen_window_if_none())
            uo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
