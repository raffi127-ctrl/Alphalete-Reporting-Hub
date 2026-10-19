"""`hub_publish.ran_ok_today` on a card SEVERAL reports publish to.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_ran_ok_today_shared_card

WHAT THIS GUARDS (2026-10-15, DD Bulletin $0). dd_week_roll publishes to the
dd_populate card. credico_fetch failed, so dd_populate never ran — and the noon
backstop read dd_week_roll's success row as "dd_populate already ran", adopted
a DONE, and the bulletin built on an empty week. On a shared card only a row
under the report's OWN name counts.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.day_orchestrator import hub_publish as hp

DAY = "2026-10-15"


def _row(card, name, status="success", at=DAY + " 09:21:26"):
    return {"Report ID": card, "Report Name": name, "Status": status,
            "Started At": at}


class _Ws:
    def __init__(self, rows):
        self._rows = rows

    def get_all_records(self):
        return self._rows


class SharedCardTest(unittest.TestCase):

    def _ask(self, rid, rows):
        with mock.patch.object(hp, "_ws", return_value=_Ws(rows)):
            return hp.ran_ok_today(rid, DAY)

    def test_sibling_row_does_not_count(self):
        rows = [_row("dd_populate", "DD — roll the week-ending column")]
        self.assertFalse(self._ask("dd_populate", rows))

    def test_own_row_counts(self):
        name = hp._display_name("dd_populate")
        self.assertTrue(name)
        rows = [_row("dd_populate", "DD — roll the week-ending column"),
                _row("dd_populate", name, at=DAY + " 10:02:00")]
        self.assertTrue(self._ask("dd_populate", rows))

    def test_arrow_spelling_still_matches(self):
        # b2b_metrics' own agent publishes "→", the config says "->".
        rows = [_row("b2b-metrics", "B2B Metrics → office channels")]
        self.assertTrue(self._ask("b2b_metrics", rows))

    def test_other_office_does_not_count(self):
        rows = [_row("office-metrics", "Rashad's Daily Metrics (#elevate-sales)")]
        self.assertFalse(self._ask("cyrus_metrics", rows))

    def test_unshared_card_unchanged(self):
        with mock.patch.object(hp, "hub_card_id", return_value="solo-card"), \
                mock.patch.object(hp, "_card_shared", return_value=False):
            rows = [_row("solo-card", "anything at all")]
            self.assertTrue(self._ask("solo", rows))


if __name__ == "__main__":
    unittest.main()
