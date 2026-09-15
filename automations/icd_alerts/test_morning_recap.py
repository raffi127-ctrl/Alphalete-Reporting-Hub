"""Yesterday's final board, in this morning's metrics thread.

Megan 2026-09-15: "for those getting knocks on the LucyECO and getting
metrics- can we make it so that their final knock board from the day prior is
posted that next morning in their metrics thread?"

The board lands through the day and is scrolled past by evening; the metrics
thread is what an owner opens the next morning. The board is the only part of
yesterday not in it, and it is the part that explains the rest.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from unittest import mock

from automations.icd_alerts import morning_recap as M

MON = dt.date(2026, 9, 14)          # a Monday
TUE = dt.date(2026, 9, 15)
SAT = dt.date(2026, 9, 12)


def _book(rows_by_day, office="kash"):
    rows = [["Office", "Day", "Rows JSON"]]
    for day, rows_json in rows_by_day.items():
        rows.append([office, day, json.dumps(rows_json)])
    tab = mock.MagicMock()
    tab.get_all_values.return_value = rows
    book = mock.MagicMock()
    book.worksheet.return_value = tab
    return book


class TheDayPriorMeansTheLastSellingDay(unittest.TestCase):
    """Not literally yesterday.

    On a Monday, yesterday is Sunday and nobody knocked. Posting an empty
    board would be wrong and posting nothing would be worse -- what an owner
    wants on Monday morning is Saturday.
    """

    def test_tuesday_takes_monday(self):
        b = _book({"2026-09-14": [{"rep": "A"}]})
        found = M.last_board_day("kash", TUE, book=b)
        self.assertEqual(found[0], MON)

    def test_monday_reaches_back_past_sunday_to_saturday(self):
        b = _book({"2026-09-12": [{"rep": "A"}]})
        found = M.last_board_day("kash", MON, book=b)
        self.assertEqual(found[0], SAT)

    def test_a_day_with_no_rows_is_not_a_day(self):
        # An empty relay row is not a board; keep walking back.
        b = _book({"2026-09-14": [], "2026-09-12": [{"rep": "A"}]})
        self.assertEqual(M.last_board_day("kash", TUE, book=b)[0], SAT)

    def test_nothing_recent_finds_nothing(self):
        b = _book({"2026-08-01": [{"rep": "A"}]})
        self.assertIsNone(M.last_board_day("kash", TUE, book=b))

    def test_another_office_is_not_borrowed_from(self):
        b = _book({"2026-09-14": [{"rep": "A"}]}, office="cyrus")
        self.assertIsNone(M.last_board_day("kash", TUE, book=b))


class WhenItPosts(unittest.TestCase):

    def _run(self, now, today=TUE):
        b = _book({"2026-09-14": [{"rep": "A"}]})
        office = mock.MagicMock(key="kash")
        with mock.patch.object(M, "eligible", return_value=[office]), \
             mock.patch.object(M, "_posted", return_value={}):
            return M.run(today, send=False, book=b, now=now,
                         log=lambda *a, **k: None)

    def test_it_runs_in_the_morning(self):
        self.assertEqual(len(self._run(dt.datetime(2026, 9, 15, 9, 0))), 1)

    def test_it_does_not_run_in_the_afternoon(self):
        # Yesterday's board dropping into an afternoon thread reads as today's.
        self.assertEqual(self._run(dt.datetime(2026, 9, 15, 14, 0)), [])

    def test_it_does_not_run_on_sunday(self):
        self.assertEqual(
            self._run(dt.datetime(2026, 9, 13, 9, 0), today=dt.date(2026, 9, 13)),
            [])

    def test_it_does_not_repeat_once_posted(self):
        # The poster ticks every couple of minutes; a recap on every tick
        # would be its own kind of broken.
        b = _book({"2026-09-14": [{"rep": "A"}]})
        office = mock.MagicMock(key="kash")
        with mock.patch.object(M, "eligible", return_value=[office]), \
             mock.patch.object(M, "_posted",
                               return_value={"2026-09-15|kash": "done"}):
            out = M.run(TUE, send=False, book=b,
                        now=dt.datetime(2026, 9, 15, 9, 0),
                        log=lambda *a, **k: None)
        self.assertEqual(out, [])


class OnlyOfficesOnBoth(unittest.TestCase):

    def test_an_office_without_metrics_has_nowhere_to_post(self):
        icd = [mock.MagicMock(key="kash"), mock.MagicMock(key="lonely")]
        with mock.patch("automations.icd_alerts.offices.active",
                        return_value=icd), \
             mock.patch("automations.office_metrics.offices.OFFICES",
                        {"kash": object()}):
            self.assertEqual([o.key for o in M.eligible()], ["kash"])


if __name__ == "__main__":
    unittest.main()
