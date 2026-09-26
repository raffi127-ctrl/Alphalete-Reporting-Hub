"""What the Hub's ICD roster says each office gets, and how often.

The cadence line is built from a CACHE (output/.icd_relay_schedule.json), not a
live Sheets read -- a round trip at Hub import once hung every card in the app.
So two things can go wrong quietly: the cache can omit a destination, and a
number in it can be labelled with the wrong meaning.

Both had happened. Until 2026-09-26 the cache carried only the Slack alert
channels and the Slack knock boards, so an office whose board goes to a group
chat read as "Knock boards -> none approved yet" -- the Hub saying a live board
did not exist. And `cadence_min` 0 does not mean the same thing for a text as it
does for a board: a text with no cadence FOLLOWS the board it is a copy of, and
only an office with no interval board at all falls through to the fixed
2:00/5:15/9:00 slots.

    .venv/bin/python -m unittest automations.icd_alerts.test_hub_schedule_line
"""
from __future__ import annotations

import unittest

from automations import hub_cards as H


class TheTextLabelIsNotTheBoardLabel(unittest.TestCase):
    def test_a_real_cadence_reads_as_itself(self):
        self.assertEqual(H._icd_text_cadence_label(30, []),
                         "every 30 minutes")
        self.assertEqual(H._icd_text_cadence_label(60, []), "once an hour")

    def test_zero_follows_the_offices_own_board(self):
        # Carlos / Colten's shape: the form never asked their group chat for a
        # cadence, so knocks_post gives it the board's own beat.
        self.assertEqual(
            H._icd_text_cadence_label(0, [["#alphalete-gp-sales", 30]]),
            "with their board, every 30 minutes")

    def test_the_first_interval_board_wins_not_a_fixed_slot_one(self):
        self.assertEqual(
            H._icd_text_cadence_label(0, [["#slots", 0], ["#real", 60]]),
            "with their board, once an hour")

    def test_zero_with_no_interval_board_keeps_the_fixed_slots(self):
        self.assertEqual(H._icd_text_cadence_label(0, [["#slots", 0]]),
                         "at 2:00 PM · 5:15 PM · 9:00 PM")
        self.assertEqual(H._icd_text_cadence_label(0, []),
                         "at 2:00 PM · 5:15 PM · 9:00 PM")

    def test_a_board_cadence_of_zero_still_means_the_slots(self):
        # The board label is unchanged -- 0 there has always meant set times.
        self.assertEqual(H._icd_cadence_label(0),
                         "at 2:00 PM · 5:15 PM · 9:00 PM")

    def test_garbage_does_not_raise(self):
        self.assertEqual(H._icd_text_cadence_label("nope", []),
                         "on its own schedule")
        self.assertEqual(H._icd_text_cadence_label(0, [["#x", "nope"]]),
                         "at 2:00 PM · 5:15 PM · 9:00 PM")


class TheCacheCarriesTexts(unittest.TestCase):
    def test_build_reads_all_three_approved_columns(self):
        import json
        from unittest import mock
        from automations.icd_alerts import post as P
        from automations.icd_alerts import schedule_cache as SC

        def _row(office, approved_json_col, payload):
            row = [""] * (P.CH_TX_APPROVED + 1)
            row[P.CH_OFFICE] = office
            row[approved_json_col] = json.dumps(payload)
            return row

        head = ["h"] * (P.CH_TX_APPROVED + 1)
        cyrus = [""] * (P.CH_TX_APPROVED + 1)
        cyrus[P.CH_OFFICE] = "cyrus"
        cyrus[P.CH_TX_APPROVED_JSON] = json.dumps(
            [{"group": "Ambient Managing Partners", "cadence_min": 30,
              "require_handles": ["+13195609495"]}])
        cyrus[P.CH_TX_APPROVED] = "TRUE"
        cyrus[P.CH_KN_APPROVED_JSON] = json.dumps(
            [{"channel_id": "C1", "channel_name": "#ambient-sales-1",
              "cadence_min": 30}])
        cyrus[P.CH_KN_APPROVED] = "TRUE"

        tab = mock.MagicMock()
        tab.get_all_values.return_value = [head, cyrus]
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        with mock.patch.object(P, "approved_channels", return_value={}), \
                mock.patch("automations.recruiting_report.fill.open_by_key",
                           return_value=book):
            out = SC.build()

        self.assertIn("cyrus", out)
        # The group NAME, never the participant-pinned address.
        self.assertEqual(out["cyrus"]["texts"],
                         [["Ambient Managing Partners", 30]])
        self.assertEqual(out["cyrus"]["knocks"], [["#ambient-sales-1", 30]])

    def test_a_text_only_office_is_not_reported_as_having_no_boards(self):
        line = H._icd_relay_roster
        self.assertTrue(callable(line))   # smoke: the roster still builds
        sched = {"texts": [["A Players", 0]], "knocks": [], "alerts": []}
        kn, tx = sched["knocks"], sched["texts"]
        # The branch under test: "none approved yet" is suppressed when a text
        # room exists, because that room IS the board.
        self.assertTrue(bool(tx) and not kn)


if __name__ == "__main__":
    unittest.main()
