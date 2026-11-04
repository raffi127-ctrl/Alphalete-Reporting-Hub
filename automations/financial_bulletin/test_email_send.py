"""python -m unittest automations.financial_bulletin.test_email_send"""
import unittest
from unittest import mock

from automations.financial_bulletin import email_send as E

GRID = [
    ["FINANCIAL BULLETIN"], ["Updated"], [""],
    ["BY ORG", ""], ["ORG", "AVG OWNERS WITHDRAWAL / DIVIDEND"], ["Carlos's Org", "$1"], [""],
    ["MONEY SAVED (Total Funds Available)", "", ""],
    ["OWNER", "10/25/26", "11/01/26"],
    ["CARLOS'S ORG", "", ""],
    ["Ann", "$1", "$2"], ["Bob", "$1", ""],
    ["Carlos's Org average", "$1", "$2"],
    ["TOTAL", "$2", "$2"],
    [""],
    ["OPERATING %", "", ""],
    ["OWNER", "10/25/26", "11/01/26"],
]


class Pure(unittest.TestCase):
    def test_blocks_split_on_blank_rows(self):
        self.assertEqual(E.blocks(GRID), [(0, 1), (3, 5), (7, 13), (15, 16)])

    def test_newest_week_skips_the_summary_header_slash(self):
        self.assertEqual(E.newest_week(GRID), ("11/01/26", 2))

    def test_filled_share_counts_owners_only(self):
        self.assertEqual(E.filled_share(GRID, 2), 0.5)

    def test_books_through_is_8_days_before_the_column(self):
        self.assertEqual(E.books_through("11/01/26"), "10/24")
        self.assertEqual(E.books_through("01/03/27"), "12/26")


class Decisions(unittest.TestCase):
    def run_main(self, argv, *, sent=False, days=1.0):
        with mock.patch.object(E.rfill, "open_by_key"), \
                mock.patch.object(E.rfill, "_client"), \
                mock.patch.object(E.rfill, "_retry", return_value=GRID), \
                mock.patch.object(E, "already_sent", return_value=sent), \
                mock.patch.object(E, "_sent_days_ago", return_value=days), \
                mock.patch.object(E, "capture", return_value=[]) as cap, \
                mock.patch.object(E, "_warn") as warn:
            self.assertEqual(E.main(argv), 0)
        return warn, cap

    def test_half_filled_week_holds_and_warns_eve(self):
        warn, cap = self.run_main(["--send"])
        warn.assert_called_once()
        cap.assert_not_called()

    def test_held_test_send_does_not_warn(self):
        warn, cap = self.run_main(["--send", "--to", "x@y"])
        warn.assert_not_called()
        cap.assert_not_called()

    def test_rerun_same_week_is_silent(self):
        with mock.patch.object(E, "MIN_FILLED", 0.1):
            warn, cap = self.run_main(["--send"], sent=True, days=1)
        warn.assert_not_called()
        cap.assert_not_called()

    def test_no_new_week_a_week_later_warns(self):
        with mock.patch.object(E, "MIN_FILLED", 0.1):
            warn, cap = self.run_main(["--send"], sent=True, days=7)
        warn.assert_called_once()
        cap.assert_not_called()

    def test_error_reaches_eve(self):
        with mock.patch.object(E, "main", side_effect=RuntimeError("boom")), \
                mock.patch.object(E, "_warn") as warn:
            E.weekly_pass()
        warn.assert_called_once()

    def test_goes_to_raf_and_maud(self):
        self.assertEqual(E.TO, ["raffi127@gmail.com", "maudmiller4@gmail.com"])


if __name__ == "__main__":
    unittest.main()
