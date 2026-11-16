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


class _Rate(Exception):
    """A gspread APIError as sheets_retry.status_code reads one."""

    def __init__(self, code=429):
        super().__init__("APIError: [{}]".format(code))
        self.code = code


class RateLimited(unittest.TestCase):
    """A 429 on this workbook is a "wait a second", not a failed office.

    Megan 2026-11-16: 11580's write came back APIError at 15:46 and opened a
    red ticket asking a person to act on a rate limit that had already
    passed."""

    def setUp(self):
        """Record the backoff instead of serving it.

        `sheets_retry.call`'s sleeper is a DEFAULT ARGUMENT bound at import,
        so patching `sheets_retry.time.sleep` does nothing and the test really
        waits 1+2+4+8+16s. Wrap the two entry points instead and hand them a
        sleeper, which is what the parameter is there for."""
        from automations.shared import sheets_retry
        self.retry = sheets_retry
        self._slept = []
        self._saved = (sheets_retry.call, sheets_retry.open_sheet)
        real_call, real_open = self._saved

        def call(fn, *a, **kw):
            kw.setdefault("sleeper", self._slept.append)
            return real_call(fn, *a, **kw)

        def open_sheet(client, sheet_id, **kw):
            kw.setdefault("sleeper", self._slept.append)
            return real_open(client, sheet_id, **kw)

        sheets_retry.call, sheets_retry.open_sheet = call, open_sheet

    def tearDown(self):
        self.retry.call, self.retry.open_sheet = self._saved

    def test_a_429_on_the_update_is_retried_and_the_write_lands(self):
        ws = FakeWorksheet()
        calls = []
        real = ws.update

        def flaky(**kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise _Rate()
            return real(**kwargs)

        ws.update = flaky
        tab, n = TAB.write("11580", INFO, PREFS, ROWS,
                           gc=FakeClient(FakeSheet(ws)))
        self.assertEqual(tab, "AI Settings 11580")
        self.assertEqual(len(calls), 3)
        self.assertTrue(ws.values, "the rows should have landed on retry")
        self.assertTrue(self._slept, "it should have backed off between tries")

    def test_a_429_opening_the_workbook_is_retried(self):
        sheet = FakeSheet(FakeWorksheet())
        tries = []

        class Flaky:
            def open_by_key(self, key):
                tries.append(key)
                if len(tries) < 2:
                    raise _Rate()
                return sheet

        TAB.write("11280", INFO, PREFS, ROWS, gc=Flaky())
        self.assertEqual(len(tries), 2)

    def test_a_429_reading_the_tab_never_creates_a_duplicate(self):
        """The old code treated ANY error from worksheet() as "no such tab"
        and added a second one — on a rate-limited minute that is a duplicate
        tab, not a missing one."""
        sheet = FakeSheet(FakeWorksheet())

        def always_rate_limited(name):
            raise _Rate()

        sheet.worksheet = always_rate_limited
        with self.assertRaises(_Rate):
            TAB.write("11280", INFO, PREFS, ROWS, gc=FakeClient(sheet))
        self.assertIsNone(sheet.added, "must not add a tab over a 429")

    def test_a_real_missing_tab_is_still_created(self):
        """403/404/WorksheetNotFound are not retryable — the old path stands."""
        sheet = FakeSheet(missing=True)
        TAB.write("11280", INFO, PREFS, ROWS, gc=FakeClient(sheet))
        self.assertEqual(sheet.added, "AI Settings 11280")
        self.assertFalse(self._slept, "a missing tab should not back off")


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


class Hours(unittest.TestCase):
    PAGE = ("Hours\nCurrent Active Interview Time\nVideo Tutorial\nM\n"
            "08:15 AM - 08:45 AM\n4\n01:00 PM - 01:30 PM\n3\nT\n"
            "09:00 AM - 09:30 AM\n2\nW\nT\nF\nS\nS\nSave")

    def test_slots_and_seats_off_the_hours_pane(self):
        from automations.sms_audit import ai_settings as AIS
        got = AIS.parse_hours(self.PAGE)
        self.assertEqual(sorted(got), ["Monday", "Tuesday"])
        self.assertEqual(got["Monday"][1], {"start": "01:00 PM",
                                            "end": "01:30 PM", "seats": 3})
        self.assertEqual(AIS.parse_hours("no list here"), {})

    def test_hours_round_trip_and_old_readers_ignore_them(self):
        from automations.sms_audit import ai_settings as AIS
        hours = AIS.parse_hours(self.PAGE)
        ws = FakeWorksheet()
        TAB.write("11280", INFO, PREFS, ROWS, gc=FakeClient(FakeSheet(ws)),
                  hours=hours)
        self.assertEqual(TAB.parse_hours(ws.values), hours)
        info, prefs, rows = TAB.parse(ws.values)        # unchanged
        self.assertEqual(len(rows), len(ROWS))
        got, when = TAB.read_hours("11280", gc=FakeClient(FakeSheet(ws)))
        self.assertEqual(got, hours)


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
