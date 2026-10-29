"""Lucy 1 hands an office Mac its SaraPlus code (code_answer), 2026-10-29.

The ways this could go wrong that matter: the wrong office's code handed out,
a code from BEFORE the request typed in, the poster blocked waiting on mail,
and a Mac left waiting nine minutes for an office nobody set up.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import code_answer as CA
from automations.icd_alerts import post as P

TZ = dt.timezone(dt.timedelta(hours=-4))
NOW = dt.datetime(2026, 10, 29, 10, 5, 0, tzinfo=TZ)


class Sheet:
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]
        self.cells = {}

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def update_cell(self, r, c, v):
        self.cells[(r, c)] = v

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))

    def update(self, rng, vals):
        self.rows[:1] = vals


class Book:
    def __init__(self, tabs):
        self.tabs = tabs

    def worksheet(self, title):
        if title not in self.tabs:
            raise KeyError(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = Sheet([])
        return self.tabs[title]


def fault_row(office, since, stage=CA.REQUEST_STAGE, posted=""):
    row = [""] * (P.F_POSTED + 1)
    row[P.F_OFFICE], row[P.F_DAY], row[P.F_STAGE] = office, "2026-10-29", stage
    row[P.F_SUMMARY] = CA.summary_for(since)
    row[P.F_POSTED] = posted
    return row


def book_with(faults, mail=None):
    tabs = {P.FAULTS_TAB: Sheet([["head"]] + faults)}
    if mail is not None:
        tabs[CA.MAIL_TAB] = Sheet([CA.MAIL_HEADER] + mail)
    return Book(tabs)


class RequestWording(unittest.TestCase):
    def test_the_instant_survives_the_round_trip(self):
        since = dt.datetime(2026, 10, 29, 10, 2, 11, tzinfo=TZ)
        self.assertEqual(CA.since_of(CA.summary_for(since)), since)

    def test_two_requests_never_share_a_summary(self):
        a = dt.datetime(2026, 10, 29, 10, 2, 11, tzinfo=TZ)
        self.assertNotEqual(CA.summary_for(a),
                            CA.summary_for(a + dt.timedelta(seconds=1)))

    def test_the_search_is_for_that_office_address_only(self):
        q = CA.query_for("luke@example.com")
        self.assertIn("to:luke@example.com", q)
        self.assertIn("from:security.info@saraplus.com", q)


class Answering(unittest.TestCase):
    def setUp(self):
        self.since = NOW - dt.timedelta(minutes=2)
        self.asked = []

    def code(self, since, query):
        self.asked.append((since, query))
        return ("482913", since + dt.timedelta(seconds=40))

    def test_a_forwarded_code_is_written_for_that_request(self):
        book = book_with([fault_row("luke", self.since)],
                         mail=[["luke", "luke@example.com", "", ""]])
        out = CA.answer_requests(book, send=True, now=NOW, newest_code=self.code,
                                 log=lambda *_: None)
        self.assertEqual(out, [{"office": "luke", "status": "ready"}])
        row = book.tabs[CA.CODES_TAB].rows[-1]
        self.assertEqual(row[:3], ["luke", self.since.isoformat(timespec="seconds"), "482913"])
        self.assertEqual(row[5], CA.STATUS_READY)
        # searched with the request's own instant, for luke's address
        self.assertEqual(self.asked[0][0], self.since)
        self.assertIn("to:luke@example.com", self.asked[0][1])
        # and the request is closed
        self.assertIn("answered", book.tabs[P.FAULTS_TAB].cells[(2, P.F_POSTED + 1)])

    def test_no_forward_set_up_answers_none_at_once(self):
        """So the Mac stops waiting and sends the DM it always sent."""
        book = book_with([fault_row("tre", self.since)], mail=[])
        out = CA.answer_requests(book, send=True, now=NOW, newest_code=self.code,
                                 log=lambda *_: None)
        self.assertEqual(out[0]["status"], CA.STATUS_NONE)
        self.assertEqual(book.tabs[CA.CODES_TAB].rows[-1][5], CA.STATUS_NONE)
        self.assertEqual(self.asked, [], "no inbox read for an office with no forward")

    def test_no_mail_yet_waits_for_the_next_tick(self):
        book = book_with([fault_row("luke", self.since)],
                         mail=[["luke", "luke@example.com", "", ""]])
        out = CA.answer_requests(book, send=True, now=NOW,
                                 newest_code=lambda s, q: None, log=lambda *_: None)
        self.assertEqual(out[0]["status"], "waiting")
        self.assertEqual(book.tabs[P.FAULTS_TAB].cells, {}, "left open")

    def test_an_old_request_expires_unanswered(self):
        old = NOW - dt.timedelta(minutes=CA.REQUEST_MAX_MIN + 1)
        book = book_with([fault_row("luke", old)],
                         mail=[["luke", "luke@example.com", "", ""]])
        out = CA.answer_requests(book, send=True, now=NOW, newest_code=self.code,
                                 log=lambda *_: None)
        self.assertEqual(out[0]["status"], "expired")
        self.assertEqual(self.asked, [])

    def test_a_broken_inbox_never_raises(self):
        def boom(s, q):
            raise OSError("imap down")
        book = book_with([fault_row("luke", self.since)],
                         mail=[["luke", "luke@example.com", "", ""]])
        out = CA.answer_requests(book, send=True, now=NOW, newest_code=boom,
                                 log=lambda *_: None)
        self.assertEqual(out[0]["status"], "inbox-error")

    def test_other_faults_and_closed_requests_are_left_alone(self):
        book = book_with([fault_row("luke", self.since, stage="signin-saraplus"),
                          fault_row("eveliz", self.since, posted="done")],
                         mail=[["luke", "luke@example.com", "", ""],
                               ["eveliz", "ev@example.com", "", ""]])
        out = CA.answer_requests(book, send=True, now=NOW, newest_code=self.code,
                                 log=lambda *_: None)
        self.assertEqual(out, [])
        self.assertEqual(self.asked, [])

    def test_a_dry_run_writes_nothing(self):
        book = book_with([fault_row("luke", self.since)],
                         mail=[["luke", "luke@example.com", "", ""]])
        CA.answer_requests(book, send=False, now=NOW, newest_code=self.code,
                           log=lambda *_: None)
        self.assertNotIn(CA.CODES_TAB, book.tabs)
        self.assertEqual(book.tabs[P.FAULTS_TAB].cells, {})


class ThePosterLeavesRequestsOpen(unittest.TestCase):
    def test_notify_faults_skips_code_requests(self):
        import inspect
        src = inspect.getsource(P.notify_faults)
        self.assertIn('"probe-code-request"', src)


if __name__ == "__main__":
    unittest.main()
