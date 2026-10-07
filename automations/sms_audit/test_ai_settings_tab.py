# -*- coding: utf-8 -*-
"""The AI Settings round-trip through the control-sheet tab.

Run: python -m unittest automations.sms_audit.test_ai_settings_tab
"""
import json
import unittest

from automations.sms_audit import ai_settings_tab as TAB

INFO = {"ai_assistant_name": "Dani Pena", "interview_type": "Zoom Meeting",
        "office_address": "5217 Tennyson Pkwy"}
PREFS = {"offered_buffer": "60", "accepted_buffer": "5",
         "ghosting_threshold": "60"}
ROWS = [{"name": "Compensation", "category": "Pay", "description": "asks pay",
         "message": "We offer weekly pay of $1,000-$1,500.",
         "routing": "Escalate"},
        {"name": 'Mentions "Scam"', "category": "Trust", "description": "",
         "message": "", "routing": "Silent Only"}]


class FakeWorksheet:
    def __init__(self, values=None):
        self.values = values or []
        self.row_count = 100
        self.cleared = False

    def clear(self):
        self.cleared = True
        self.values = []

    def resize(self, rows=None, cols=None):
        self.row_count = rows or self.row_count

    def update(self, values=None, range_name=None, raw=None):
        self.values = values

    def get_all_values(self):
        return self.values


class FakeSheet:
    def __init__(self, ws=None, missing=False):
        self.ws = ws or FakeWorksheet()
        self.missing = missing
        self.added = None

    def worksheet(self, name):
        if self.missing:
            raise RuntimeError("WorksheetNotFound: " + name)
        return self.ws

    def add_worksheet(self, title, rows=None, cols=None):
        self.added = title
        self.missing = False
        return self.ws


class FakeClient:
    def __init__(self, sheet):
        self.sheet = sheet

    def open_by_key(self, key):
        return self.sheet


class RoundTrip(unittest.TestCase):
    def test_what_is_written_is_what_comes_back(self):
        ws = FakeWorksheet()
        tab, n = TAB.write("11280", INFO, PREFS, ROWS,
                           gc=FakeClient(FakeSheet(ws)))
        self.assertEqual(tab, "AI Settings 11280")
        self.assertEqual(n, len(ws.values))
        info, prefs, rows = TAB.parse(ws.values)
        self.assertEqual(info, INFO)
        self.assertEqual(prefs, PREFS)
        self.assertEqual([r["name"] for r in rows],
                         ["Compensation", 'Mentions "Scam"'])
        self.assertEqual(rows[1]["routing"], "Silent Only")

    def test_a_missing_tab_is_created(self):
        sheet = FakeSheet(missing=True)
        TAB.write("24065", INFO, PREFS, ROWS, gc=FakeClient(sheet))
        self.assertEqual(sheet.added, "AI Settings 24065")

    def test_an_existing_tab_is_cleared_first(self):
        ws = FakeWorksheet([["stale"], ["rows"]])
        TAB.write("11280", INFO, PREFS, ROWS, gc=FakeClient(FakeSheet(ws)))
        self.assertTrue(ws.cleared)
        self.assertNotIn(["stale"], ws.values)

    def test_a_message_with_a_comma_and_quotes_survives(self):
        ws = FakeWorksheet()
        tricky = [{"name": "Remote Work", "category": "", "description": "",
                   "message": 'No, this is in office. Is that "ok"?',
                   "routing": "Clarify"}]
        TAB.write("11280", {}, {}, tricky, gc=FakeClient(FakeSheet(ws)))
        _i, _p, rows = TAB.parse(ws.values)
        self.assertEqual(rows[0]["message"],
                         'No, this is in office. Is that "ok"?')


class Parsing(unittest.TestCase):
    def test_empty_tab_is_not_a_pull(self):
        self.assertEqual(TAB.parse([]), (None, None, []))

    def test_header_only_tab_is_not_a_pull(self):
        self.assertEqual(TAB.parse([["pulled x"], list(TAB.COLUMNS)]),
                         (None, None, []))

    def test_blank_rows_are_skipped(self):
        vals = [["pulled x"], list(TAB.COLUMNS),
                [], ["", "", ""], ["preferences", "offered_buffer", "60"]]
        _i, prefs, _r = TAB.parse(vals)
        self.assertEqual(prefs, {"offered_buffer": "60"})

    def test_unreadable_escalation_json_keeps_the_name(self):
        vals = [["pulled x"], list(TAB.COLUMNS),
                ["escalation", "Compensation", "{not json"]]
        _i, _p, rows = TAB.parse(vals)
        self.assertEqual(rows[0]["name"], "Compensation")
        self.assertEqual(rows[0]["routing"], "")


class Reading(unittest.TestCase):
    def test_read_reports_a_source_when_there_is_data(self):
        ws = FakeWorksheet()
        TAB.write("11280", INFO, PREFS, ROWS, gc=FakeClient(FakeSheet(ws)))
        info, prefs, rows, src = TAB.read("11280",
                                          gc=FakeClient(FakeSheet(ws)))
        self.assertIn("AI Settings 11280", src)
        self.assertEqual(info["ai_assistant_name"], "Dani Pena")
        self.assertEqual(len(rows), 2)

    def test_an_empty_tab_reports_no_source(self):
        got = TAB.read("11280", gc=FakeClient(FakeSheet(FakeWorksheet())))
        self.assertEqual(got, (None, None, [], None))

    def test_an_unreachable_sheet_is_not_pulled_rather_than_a_crash(self):
        class Boom:
            def open_by_key(self, key):
                raise RuntimeError("429 rate limited")
        self.assertEqual(TAB.read("11280", gc=Boom()),
                         (None, None, [], None))


if __name__ == "__main__":
    unittest.main()
