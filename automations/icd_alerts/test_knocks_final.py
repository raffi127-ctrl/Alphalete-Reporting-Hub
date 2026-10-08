"""A room's FINAL knocks board of the night (Roshan/Amin 2026-09-29: "a final
disposition report at like 7pm every night"). `final_at` on the approved
destination, Mon-Fri, on the office's clock, even after the bell."""
import datetime as dt
import json
import unittest

from automations.icd_alerts import knocks_post as K, post as P

WED = dt.date(2026, 9, 30)
SAT = dt.date(2026, 10, 3)
SUN = dt.date(2026, 10, 4)
ROOM = {"channel_id": "C08A6P32VB3", "cadence_min": 60, "final_at": "19:00"}


def _at(day, h, m):
    return dt.datetime.combine(day, dt.time(h, m))


class FinalDueTest(unittest.TestCase):
    def test_due_just_past_seven(self):
        self.assertTrue(K.final_due(ROOM, _at(WED, 18, 20), _at(WED, 19, 5)))
        self.assertTrue(K.final_due(ROOM, None, _at(WED, 19, 0)))

    def test_once_only(self):
        self.assertFalse(K.final_due(ROOM, _at(WED, 19, 5), _at(WED, 19, 15)))

    def test_not_before_or_long_after(self):
        self.assertFalse(K.final_due(ROOM, None, _at(WED, 18, 59)))
        self.assertFalse(K.final_due(ROOM, None, _at(WED, 19, 41)))

    def test_weekdays_only(self):
        # Saturday keeps the 6pm board stop; Sunday is not a selling day.
        self.assertFalse(K.final_due(ROOM, None, _at(SAT, 19, 5)))
        self.assertFalse(K.final_due(ROOM, None, _at(SUN, 19, 5)))

    def test_room_without_final_is_untouched(self):
        plain = {"channel_id": "C1", "cadence_min": 60}
        self.assertFalse(K.final_due(plain, None, _at(WED, 19, 5)))
        # An hourly room posted at 18:20 is not due at 19:05 without a final...
        self.assertFalse(K.is_due(plain, _at(WED, 18, 20), _at(WED, 19, 5)))
        # ...and is with one, ahead of its own hour.
        self.assertTrue(K.is_due(ROOM, _at(WED, 18, 20), _at(WED, 19, 5)))

    def test_bad_time_is_no_final(self):
        self.assertFalse(K.final_due(dict(ROOM, final_at="7pm"), None,
                                     _at(WED, 19, 5)))

    def test_caption_says_final(self):
        self.assertIn("Final", K._final_comment(_at(WED, 19, 5)))
        self.assertIn("7:05 PM", K._final_comment(_at(WED, 19, 5)))


class _Tab:
    def __init__(self, rows):
        self.rows, self.writes = rows, []

    def get_all_values(self):
        return self.rows

    def update(self, values, range_name):
        self.writes.append((range_name, values))


class _Book:
    def __init__(self, tab):
        self.tab = tab

    def worksheet(self, name):
        return self.tab


def _row(key, dests):
    row = [""] * 17
    row[P.CH_OFFICE] = key
    row[P.CH_KN_APPROVED_JSON] = json.dumps(dests)
    row[P.CH_KN_APPROVED] = "TRUE"
    return row


class SetFinalTest(unittest.TestCase):
    def test_writes_column_k_only(self):
        tab = _Tab([["hdr"], _row("roshan", [{"channel_id": "C1",
                                               "cadence_min": 60}])])
        self.assertTrue(P.set_knocks_final("roshan", "19:00", book=_Book(tab)))
        rng, vals = tab.writes[0]
        self.assertEqual(rng, "K2")
        self.assertEqual(json.loads(vals[0][0])[0]["final_at"], "19:00")

    def test_blank_removes(self):
        tab = _Tab([["hdr"], _row("roshan", [dict(ROOM)])])
        P.set_knocks_final("roshan", "", book=_Book(tab))
        self.assertNotIn("final_at", json.loads(tab.writes[0][1][0][0])[0])

    def test_bad_time_refused(self):
        with self.assertRaises(ValueError):
            P.set_knocks_final("roshan", "7pm", book=_Book(_Tab([["hdr"]])))


if __name__ == "__main__":
    unittest.main()


class EveryRoomGetsADayEndFinal(unittest.TestCase):
    """Megan 2026-10-08: "tie last call to each office's day end". A room with
    no final_at takes the office's day_end (sat_end on a Saturday the office
    works), so the last-call line reaches every office, not just the rooms
    with a set final time."""

    class Office:
        day_end = "20:45"
        sat_end = "18:00"
        saturday = True

    PLAIN = {"channel_id": "C1", "cadence_min": 30}

    def test_due_just_past_the_day_end(self):
        o = self.Office()
        self.assertTrue(K.final_due(self.PLAIN, _at(WED, 20, 20), _at(WED, 20, 50), o))
        self.assertTrue(K.is_due(self.PLAIN, _at(WED, 20, 40), _at(WED, 20, 46), o))

    def test_not_before_and_not_twice(self):
        o = self.Office()
        self.assertFalse(K.final_due(self.PLAIN, None, _at(WED, 20, 30), o))
        self.assertFalse(K.final_due(self.PLAIN, _at(WED, 20, 47), _at(WED, 20, 55), o))

    def test_saturday_uses_sat_end_and_sunday_never(self):
        o = self.Office()
        self.assertTrue(K.final_due(self.PLAIN, None, _at(SAT, 18, 5), o))
        self.assertFalse(K.final_due(self.PLAIN, None, _at(SUN, 20, 50), o))
        o.saturday = False
        self.assertFalse(K.final_due(self.PLAIN, None, _at(SAT, 18, 5), o))

    def test_a_set_final_time_still_wins(self):
        o = self.Office()
        self.assertTrue(K.final_due(ROOM, None, _at(WED, 19, 5), o))
        self.assertFalse(K.final_due(ROOM, None, _at(WED, 20, 50), o))

    def test_without_an_office_nothing_changes(self):
        self.assertFalse(K.final_due(self.PLAIN, None, _at(WED, 20, 50)))
