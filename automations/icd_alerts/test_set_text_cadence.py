"""Retiming an office's TEXT destination writes one cell and nothing else.

Cyrus asked Raf to slow his knock reports down (2026-09-26: "How often do you
want them?" -> "Every 30."), which is the second cadence change to his row in
two days. Before this there was no named way to do it -- set_knocks_cadence
writes the KNOCKS column (K:L) and _write_texts_approval rebuilds the JSON from
the office's signup record, so it would put the form's number back.

What these pin is the three ways a hand-edit of that cell goes wrong silently:
the office's own columns getting written (which CLEARS the approval and cost
Cyrus a day of boards on 2026-09-15), the approval flag riding along with a
setting change, and another office's row moving.

    .venv/bin/python -m unittest automations.icd_alerts.test_set_text_cadence
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.icd_alerts import post as P

CYRUS = [{"group": "Ambient Managing Partners",
          "chat_guid": "any;+;4a0f39ca3b224acc906a049b63bc4c45",
          "require_handles": ["+13195609495", "+19039311920", "+19453843860"],
          "cadence_min": 15}]


def _rows(*offices):
    """An Office Channels grid: (office_key, approved_json, approved) each."""
    head = ["h"] * (P.CH_TX_APPROVED + 1)
    out = [head]
    for key, payload, approved in offices:
        row = [""] * (P.CH_TX_APPROVED + 1)
        row[P.CH_OFFICE] = key
        # The office's OWN columns carry a DIFFERENT number on purpose: that
        # disagreement is the record of what they asked for vs what we granted,
        # and a write that "tidies" it un-approves them on their next sweep.
        row[P.CH_TX_JSON] = json.dumps([{"group": "Ambient Managing Partners",
                                         "cadence_min": 15}])
        row[P.CH_TX_APPROVED_JSON] = json.dumps(payload)
        row[P.CH_TX_APPROVED] = approved
        out.append(row)
    return out


def _book(rows):
    tab = mock.MagicMock()
    tab.get_all_values.return_value = rows
    book = mock.MagicMock()
    book.worksheet.return_value = tab
    return book


class ItWritesOneCell(unittest.TestCase):
    def test_the_cadence_changes_and_nothing_else_in_the_blob_does(self):
        book = _book(_rows(("cyrus", CYRUS, "TRUE")))
        changed, before, after = P.set_text_cadence(
            "cyrus", 30, book=book, dry_run=False)
        self.assertTrue(changed)
        self.assertEqual(json.loads(before)[0]["cadence_min"], 15)
        got = json.loads(after)
        self.assertEqual(got[0]["cadence_min"], 30)
        # The address is the participants, not the name — it must survive.
        self.assertEqual(got[0]["require_handles"], CYRUS[0]["require_handles"])
        self.assertEqual(got[0]["chat_guid"], CYRUS[0]["chat_guid"])
        self.assertEqual(got[0]["group"], "Ambient Managing Partners")

    def test_column_P_only_never_the_approval_flag_beside_it(self):
        book = _book(_rows(("cyrus", CYRUS, "TRUE")))
        P.set_text_cadence("cyrus", 30, book=book, dry_run=False)
        tab = book.worksheet.return_value
        (kwargs,) = [c.kwargs for c in tab.update.call_args_list]
        self.assertEqual(kwargs["range_name"], "P2")
        self.assertEqual(len(kwargs["values"][0]), 1)

    def test_it_never_writes_the_offices_own_columns(self):
        book = _book(_rows(("cyrus", CYRUS, "TRUE")))
        P.set_text_cadence("cyrus", 30, book=book, dry_run=False)
        for call in book.worksheet.return_value.update.call_args_list:
            rng = call.kwargs["range_name"]
            for ours_only in ("N", "O"):
                self.assertFalse(rng.startswith(ours_only), rng)

    def test_an_unapproved_office_stays_unapproved(self):
        book = _book(_rows(("cyrus", CYRUS, "FALSE")))
        changed, _, _ = P.set_text_cadence("cyrus", 30, book=book,
                                          dry_run=False)
        self.assertTrue(changed)          # the setting is still a setting
        self.assertEqual(P.approved_texts(book), {})   # still not served


class ItTouchesOneOfficeOnly(unittest.TestCase):
    def test_another_offices_row_is_not_written(self):
        book = _book(_rows(("kash", [{"group": "Reporting",
                                      "cadence_min": 15}], "TRUE"),
                           ("cyrus", CYRUS, "TRUE")))
        changed, _, _ = P.set_text_cadence("cyrus", 30, book=book,
                                          dry_run=False)
        self.assertTrue(changed)
        (kwargs,) = [c.kwargs for c in
                     book.worksheet.return_value.update.call_args_list]
        self.assertEqual(kwargs["range_name"], "P3")   # cyrus's row, not kash's

    def test_an_office_with_no_text_row_is_a_no_op(self):
        book = _book(_rows(("kash", [{"group": "Reporting"}], "TRUE")))
        changed, _, _ = P.set_text_cadence("cyrus", 30, book=book,
                                          dry_run=False)
        self.assertFalse(changed)
        self.assertEqual(book.worksheet.return_value.update.call_args_list, [])

    def test_group_narrows_it_to_one_room(self):
        two = [{"group": "Ambient Managing Partners", "cadence_min": 15},
               {"group": "A Players", "cadence_min": 15}]
        book = _book(_rows(("cyrus", two, "TRUE")))
        _, _, after = P.set_text_cadence("cyrus", 30, book=book,
                                        group="A Players", dry_run=False)
        got = json.loads(after)
        self.assertEqual(got[0]["cadence_min"], 15)    # untouched
        self.assertEqual(got[1]["cadence_min"], 30)


class DryRunIsTheDefault(unittest.TestCase):
    def test_nothing_is_written_unless_asked(self):
        book = _book(_rows(("cyrus", CYRUS, "TRUE")))
        changed, before, after = P.set_text_cadence("cyrus", 30, book=book)
        self.assertTrue(changed)
        self.assertNotEqual(before, after)             # it shows the diff
        self.assertEqual(book.worksheet.return_value.update.call_args_list, [])


class ThePosterReadsTheNewNumber(unittest.TestCase):
    def test_thirty_comes_back_out_of_the_approved_column(self):
        rows = _rows(("cyrus", CYRUS, "TRUE"))
        book = _book(rows)
        _, _, after = P.set_text_cadence("cyrus", 30, book=book, dry_run=False)
        rows[1][P.CH_TX_APPROVED_JSON] = after          # as the sheet now reads
        d = P.approved_texts(book)["cyrus"][0]
        self.assertEqual(d["cadence_min"], 30)
        # Pinned to its people, so a rename cannot mint a new address/marker.
        self.assertEqual(d["channel_id"],
                         P.text_dest_address("Ambient Managing Partners",
                                             CYRUS[0]["require_handles"]))


if __name__ == "__main__":
    unittest.main()
