"""'No dispositions from' at 2:30/2:45/3:00/3:15 off the Stations car-ride grid."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_oof import config as C
from automations.nds_oof import run as R

GRID = [["Fernando Salazar", "Eduardo Alvarez", "", ""],
        ["Andrew De La Torre", "Roseanna Jurado", "Jose Manuel Pimentel Lugo", ""],
        ["Cinthya Reyes", "Nathaly Benitez", "", ""],
        ["", "", "", ""]]
ROWS = [{"Rep": "Fernando Salazar", "Total Knocks": "12"},
        {"Rep": "Eduardo Alvarez", "Total Knocks": "0"},
        {"Rep": "Jose Pimentel Lugo", "Total Knocks": "3"},
        {"Rep": "nathaly benitez", "Total Knocks": "7"}]


class NoDispo(unittest.TestCase):
    def test_slot_on_the_tick_and_within_grace(self):
        self.assertEqual(R.no_dispo_slot(dt.datetime(2026, 11, 6, 14, 30, 5)), "14:30")   # Fri
        self.assertEqual(R.no_dispo_slot(dt.datetime(2026, 11, 6, 15, 15, 40)), "15:15")
        self.assertEqual(R.no_dispo_slot(dt.datetime(2026, 11, 6, 14, 41, 0)), "14:30")   # late tick
        self.assertIsNone(R.no_dispo_slot(dt.datetime(2026, 11, 6, 14, 29, 0)))
        self.assertIsNone(R.no_dispo_slot(dt.datetime(2026, 11, 6, 15, 30, 5)))
        self.assertIsNone(R.no_dispo_slot(dt.datetime(2026, 11, 7, 14, 30, 5)))           # Sat

    def test_station_names_flatten_dedupe(self):
        self.assertEqual(R.station_names(GRID + [["Fernando Salazar"]]),
                         ["Fernando Salazar", "Eduardo Alvarez", "Andrew De La Torre",
                          "Roseanna Jurado", "Jose Manuel Pimentel Lugo", "Cinthya Reyes",
                          "Nathaly Benitez"])

    def test_missing_is_no_row_or_zero_knocks(self):
        names = R.station_names(GRID)
        self.assertEqual(R.no_dispo_names(names, ROWS),
                         ["Eduardo Alvarez", "Andrew De La Torre", "Roseanna Jurado", "Cinthya Reyes"])

    def test_wording(self):
        self.assertEqual(R.no_dispo_text(["A B", "C D"], "14:30"),
                         "No dispositions from (2:30 PM): A B, C D")
        self.assertEqual(R.no_dispo_text([], "15:15"),
                         "Everyone on the lineup has dispositioned! (3:15 PM)")

    def test_everyone_dispositioned_still_sends(self):
        rows = [{"Rep": n, "Total Knocks": "3"} for n in R.station_names(GRID)]
        with mock.patch.object(R, "_read_station_names", lambda: R.station_names(GRID)), \
             mock.patch.object(R, "borrowed_rows", lambda today, own: []), \
             mock.patch.object(R, "_log"):
            now = dt.datetime(2026, 11, 6, 15, 15, 5)
            msg = R._no_dispo_message(now.date(), now, rows, {}, send=True)
        self.assertEqual(msg, "Everyone on the lineup has dispositioned! (3:15 PM)")

    def test_message_once_per_slot_and_off_by_default(self):
        state = {}
        with mock.patch.object(R, "_read_station_names", lambda: R.station_names(GRID)), \
             mock.patch.object(R, "borrowed_rows", lambda today, own: [{"Rep": "Cinthya Reyes", "Total Knocks": "4"}]), \
             mock.patch.object(R, "_log"):
            now = dt.datetime(2026, 11, 6, 14, 30, 5)
            msg = R._no_dispo_message(now.date(), now, ROWS, state, send=True)
            self.assertEqual(msg, "No dispositions from (2:30 PM): Eduardo Alvarez, "
                                  "Andrew De La Torre, Roseanna Jurado")
            self.assertEqual(state["no_dispo_slot"], "2026-11-06 14:30")
            self.assertEqual(R._no_dispo_message(now.date(), now, ROWS, state, send=True), "")
            # a dry run never marks the slot
            state2 = {}
            R._no_dispo_message(now.date(), now, ROWS, state2, send=False)
            self.assertNotIn("no_dispo_slot", state2)
        self.assertTrue(C.NO_DISPO_SEND)    # Carlos 2026-11-06: ATT B2B Leaders text chain only

    def test_route_is_att_b2b_leaders_only(self):
        from automations.b2b_dispositions import config as B
        self.assertEqual(B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND_NO_DISPO)], [B.TEXT_GROUP_ATT])


class SlotPulls(unittest.TestCase):
    def test_a_slot_alone_makes_the_tick_pull(self):
        """3:15 on 2026-11-06: board + gaps not due, so the tick returned
        'nothing due' and never checked. The slot itself must pull."""
        now = dt.datetime(2026, 11, 6, 15, 15, 5)
        state = {"board_at": "2026-11-06T15:05:10", "gaps_at": "2026-11-06T15:05:10"}
        seen = {}

        def fake_pull(today, *, want_board, headless=True):
            seen["pulled"] = True
            return [], []

        with mock.patch.object(R, "_state", lambda: dict(state)), \
             mock.patch.object(R, "_save", lambda st: None), \
             mock.patch.object(R, "in_window", lambda n: True), \
             mock.patch.object(R, "_week_due", lambda st, n: False), \
             mock.patch.object(R, "_week_monday_due", lambda st, n: False), \
             mock.patch.object(R, "pull", fake_pull), \
             mock.patch.object(R, "_read_station_names", lambda: ["A B"]), \
             mock.patch.object(R, "borrowed_rows", lambda today, own: []), \
             mock.patch.object(R, "_callout", lambda *a, **k: ""), \
             mock.patch.object(R, "_log"):
            rc = R.tick(send=False, force=False, board=False, now=now)
        self.assertEqual(rc, 0)
        self.assertTrue(seen.get("pulled"), "the slot did not make the tick pull")

    def test_no_slot_and_nothing_due_still_skips(self):
        now = dt.datetime(2026, 11, 6, 15, 25, 5)   # not a slot
        state = {"board_at": "2026-11-06T15:05:10", "gaps_at": "2026-11-06T15:20:10"}
        with mock.patch.object(R, "_state", lambda: dict(state)), \
             mock.patch.object(R, "in_window", lambda n: True), \
             mock.patch.object(R, "_week_due", lambda st, n: False), \
             mock.patch.object(R, "_week_monday_due", lambda st, n: False), \
             mock.patch.object(R, "_board_due", lambda st, n: False), \
             mock.patch.object(R, "_due", lambda st, k, e, n: False), \
             mock.patch.object(R, "pull", side_effect=AssertionError("must not pull")), \
             mock.patch.object(R, "_log"):
            self.assertEqual(R.tick(send=False, force=False, board=False, now=now), 0)


if __name__ == "__main__":
    unittest.main()
