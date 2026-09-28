"""mark.tint paints the person, not the row number it was handed.

Megan 2026-09-28: Leo Fan had his documents and no green cell, while Patrick
Eaddy, who was never sent, had one. The office edits this tab all morning, and
a pass can be half an hour between reading a row number and painting it.
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

from automations.digi_docs import mark


class _WS:
    title = "D2D OBCL 9.28"
    id = 0

    def __init__(self):
        self.requests = []
        self.spreadsheet = types.SimpleNamespace(
            batch_update=lambda body: self.requests.append(body))

    def get_all_values(self):
        return [["whatever the sheet says now"]]


def _cand(name, row, col=13):
    return types.SimpleNamespace(name=name, row=row, digi_col=col)


def _painted_rows(ws):
    return [r["repeatCell"]["range"]["startRowIndex"] + 1
            for body in ws.requests for r in body["requests"]]


class TintFollowsThePerson(unittest.TestCase):
    def _tint(self, handed, now_on_tab):
        ws = _WS()
        with mock.patch.object(mark, "_rows_as_they_are_now",
                               wraps=mark._rows_as_they_are_now), \
             mock.patch("automations.digi_docs.roster.candidates",
                        lambda values, title: now_on_tab):
            mark.tint(ws, handed, dry_run=False)
        return ws

    def test_a_row_that_moved_is_painted_where_the_person_is_now(self):
        ws = self._tint([_cand("Leo Fan", 42)],
                        [_cand("Leo Fan", 41), _cand("Patrick Eaddy", 23)])
        self.assertEqual([41], _painted_rows(ws),
                         "paint the person, not the stale row")

    def test_somebody_off_the_tab_is_not_painted_at_all(self):
        ws = self._tint([_cand("Leo Fan", 42)], [_cand("Patrick Eaddy", 23)])
        self.assertEqual([], _painted_rows(ws),
                         "that row may now be somebody else")

    def test_an_unreadable_tab_still_paints_what_it_was_handed(self):
        ws = _WS()
        ws.get_all_values = lambda: (_ for _ in ()).throw(RuntimeError("429"))
        mark.tint(ws, [_cand("Leo Fan", 42)], dry_run=False)
        self.assertEqual([42], _painted_rows(ws),
                         "a failed re-read must not cost the mark entirely")


if __name__ == "__main__":
    unittest.main()
