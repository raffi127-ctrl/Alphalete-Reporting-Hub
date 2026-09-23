"""The relay → history backfill: what it files, and what it refuses. No network."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_sales_board import knocks_backfill as B


class Office:
    def __init__(self, owner, campaign="att", active=True):
        self.owner, self.campaign, self.active = owner, campaign, active


DAY = dt.date(2026, 9, 21)


class NameTests(unittest.TestCase):
    def test_a_lowercase_registry_name_is_title_cased(self):
        self.assertEqual(B._office_name(Office("carlos hidalgo")),
                         "Carlos Hidalgo")

    def test_a_proper_name_is_left_alone(self):
        # 'McSpadden' must not become 'Mcspadden'.
        self.assertEqual(B._office_name(Office("Ryan McSpadden")),
                         "Ryan McSpadden")

    def test_one_owner_two_feeds_get_the_campaign_appended(self):
        offices = {"carlos": Office("carlos hidalgo", "b2b_box"),
                   "carlos-b2batt": Office("carlos hidalgo", "b2b_att"),
                   "ryan": Office("Ryan McSpadden", "b2b_box")}
        names = B._names_for_run(offices, offices)
        self.assertEqual(names["carlos"], "Carlos Hidalgo — Box")
        self.assertEqual(names["carlos-b2batt"], "Carlos Hidalgo — AT&T B2B")
        # An office with one feed keeps its plain name.
        self.assertEqual(names["ryan"], "Ryan McSpadden")


class AlreadyHaveTests(unittest.TestCase):
    def test_an_exact_match_counts(self):
        have = {"2026-09-21": {"khalil mansour"}}
        self.assertTrue(B.already_have(have, "Khalil Mansour", DAY))

    def test_a_substring_office_cell_counts(self):
        # The tab spells one office 'Next Horizon Group, Inc. Nii Tagoe'.
        have = {"2026-09-21": {"next horizon group, inc. nii tagoe"}}
        self.assertTrue(B.already_have(have, "Nii Tagoe", DAY))

    def test_another_spelling_of_the_same_office_counts(self):
        # THE ONE THAT MATTERED: Kash relays as 'Kash Rai' and the scrape had
        # already filed him as 'Akashdeep Rai'. An exact check doubles his days.
        with mock.patch("automations.icd_sales_board.knocks_log._wanted",
                        return_value={"kash rai", "akashdeep rai"}):
            have = {"2026-09-21": {"akashdeep rai"}}
            self.assertEqual(B.already_have(have, "Kash Rai", DAY),
                             "akashdeep rai")

    def test_a_different_office_does_not_count(self):
        have = {"2026-09-21": {"cyrus wade"}}
        self.assertEqual(B.already_have(have, "Khalil Mansour", DAY), "")

    def test_a_different_day_does_not_count(self):
        have = {"2026-09-20": {"khalil mansour"}}
        self.assertEqual(B.already_have(have, "Khalil Mansour", DAY), "")

    def test_two_campaigns_of_one_owner_do_not_mask_each_other(self):
        have = {"2026-09-21": {"carlos hidalgo — box"}}
        self.assertEqual(
            B.already_have(have, "Carlos Hidalgo — AT&T B2B", DAY), "")


class RelayDayTests(unittest.TestCase):
    def test_the_last_row_of_a_repeated_office_day_wins(self):
        values = [["Office", "Day", "Records"],
                  ["kash", "2026-09-21", "[1]"],
                  ["kash", "2026-09-21", "[1,2]"]]
        got = B._relay_days(values, [DAY])
        self.assertEqual(got[("kash", DAY)][2], "[1,2]")

    def test_a_day_outside_the_window_is_dropped(self):
        values = [["Office", "Day"], ["kash", "2026-09-01"]]
        self.assertEqual(B._relay_days(values, [DAY]), {})

    def test_an_unreadable_day_is_skipped_not_fatal(self):
        values = [["Office", "Day"], ["kash", "not a date"], ["", ""]]
        self.assertEqual(B._relay_days(values, [DAY]), {})


class RowsForTests(unittest.TestCase):
    def test_an_inactive_office_is_refused(self):
        rows, why = B.rows_for("x", DAY, [""] * 10, Office("X", active=False))
        self.assertIsNone(rows)
        self.assertIn("active", why)

    def test_a_missing_office_is_refused(self):
        rows, why = B.rows_for("x", DAY, [""] * 10, None)
        self.assertIsNone(rows)


if __name__ == "__main__":
    unittest.main()


class AppendDayGuardTests(unittest.TestCase):
    """The guard that actually failed: append_day must refuse a day the tab
    already holds under ANY spelling of that office, whichever writer got
    there first."""

    def _ws(self, existing):
        ws = mock.Mock()
        ws.get_all_values.return_value = existing
        ws.append_rows.return_value = None
        return ws

    def _run(self, existing, office):
        from automations.icd_sales_board import knocks_log as KL
        ws = self._ws(existing)
        book = mock.Mock()
        book.worksheet.return_value = ws
        with mock.patch(
                "automations.recruiting_report.fill.open_by_key",
                return_value=book), \
             mock.patch.object(KL, "_columns",
                               return_value=["Date", "Office", "Rep"]), \
             mock.patch.object(KL, "_wanted",
                               return_value={"kash rai", "akashdeep rai"}):
            n = KL.append_day(dt.date(2026, 9, 22), office,
                              [{"Rep": "A"}], verbose=False)
        return n, ws

    def test_the_same_spelling_is_skipped(self):
        n, ws = self._run([["Date", "Office", "Rep"],
                           ["2026-09-22", "Kash Rai", "A"]], "Kash Rai")
        self.assertEqual(n, 0)
        ws.append_rows.assert_not_called()

    def test_another_spelling_of_the_same_office_is_skipped(self):
        # Kash, 2026-09-23: backfill wrote 'Kash Rai' at 04:30, the scrape
        # then wrote 'Akashdeep Rai' and his board read 3,630 against 1,815.
        n, ws = self._run([["Date", "Office", "Rep"],
                           ["2026-09-22", "Kash Rai", "A"]], "Akashdeep Rai")
        self.assertEqual(n, 0)
        ws.append_rows.assert_not_called()

    def test_a_genuinely_new_day_is_written(self):
        n, ws = self._run([["Date", "Office", "Rep"],
                           ["2026-09-21", "Kash Rai", "A"]], "Akashdeep Rai")
        self.assertEqual(n, 1)
        ws.append_rows.assert_called_once()
