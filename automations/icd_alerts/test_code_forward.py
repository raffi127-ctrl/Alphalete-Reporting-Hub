"""Setup asks for the SaraPlus code forward on the spot (code_forward), and
Lucy 1 files the address (code_answer.record_forwards). 2026-10-29.

What must hold: the address the owner picks is the one sent, and sent WITHOUT
the scrub that would blank it; skipping sends nothing and asks again later;
Lucy 1 keeps one row per office and tells Megan + Eve.
"""
from __future__ import annotations

import datetime as dt
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import code_answer as CA
from automations.icd_alerts import code_forward as CF
from automations.icd_alerts import post as P
from automations.icd_alerts import relay as R
from automations.icd_alerts.test_code_answer import Book, Sheet

TZ = dt.timezone(dt.timedelta(hours=-4))
NOW = dt.datetime(2026, 10, 29, 12, 30, 0, tzinfo=TZ)


class FakeAsk:
    class Cancelled(Exception):
        pass

    def __init__(self, pick, typed=""):
        self.pick, self.typed, self.shown = pick, typed, []

    def message(self, body, **_):
        self.shown.append(body)

    def choose(self, prompt, options):
        if self.pick is None:
            raise self.Cancelled()
        return self.pick

    def text(self, prompt):
        return self.typed


class OnTheMac(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(CF, "MARK_PATH", Path(tmp.name) / "fwd.txt")
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(CF.C, "creds", return_value={"email": "owner@gmail.com"})
        p.start()
        self.addCleanup(p.stop)
        self.sent = []
        p = mock.patch.object(R, "report_forward",
                              side_effect=lambda a, **k: self.sent.append(a) or True)
        p.start()
        self.addCleanup(p.stop)

    def _go(self, ask):
        return CF.walk_through(ask, say=lambda *_: None)

    def test_the_login_email_is_offered_and_sent(self):
        ask = FakeAsk(CF.YES)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.sent, ["owner@gmail.com"])
        self.assertIn("alphaletereporting@gmail.com", ask.shown[0])
        self.assertTrue(CF.already_set_up())

    def test_a_different_address_is_typed(self):
        self.assertEqual(self._go(FakeAsk(CF.OTHER, "codes@office.com")), "done")
        self.assertEqual(self.sent, ["codes@office.com"])

    def test_skip_or_cancel_sends_nothing_and_asks_again(self):
        for ask in (FakeAsk(CF.LATER), FakeAsk(None), FakeAsk(CF.OTHER, "nope")):
            self.assertEqual(self._go(ask), "skipped for now")
        self.assertEqual(self.sent, [])
        self.assertFalse(CF.already_set_up())


class RealReportForward(unittest.TestCase):
    def test_sends_the_address_on_the_fault_road(self):
        import json
        rec = {"office_key": "luke", "relay_key": "k", "relay_url": "u"}
        posted = []
        with mock.patch.object(R, "_endpoint", return_value=rec), \
             mock.patch.object(R, "_post",
                               side_effect=lambda u, b: posted.append(json.loads(b))
                               or '{"ok": true}'):
            self.assertTrue(R.report_forward("owner@gmail.com"))
        fault = posted[0]["fault"]
        self.assertEqual(fault["stage"], CA.FORWARD_STAGE)
        self.assertEqual(CA.address_of(fault["summary"]), "owner@gmail.com")


def fwd_row(office, address):
    row = [""] * (P.F_POSTED + 1)
    row[P.F_OFFICE], row[P.F_DAY], row[P.F_STAGE] = office, "2026-10-29", CA.FORWARD_STAGE
    row[P.F_SUMMARY] = CA.forward_summary(address)
    return row


class OnLucy1(unittest.TestCase):
    def setUp(self):
        self.told = []

    def _run(self, book, send=True):
        return CA.record_forwards(book, send=send, now=NOW, tell=self.told.append,
                                  log=lambda *_: None)

    def test_a_new_office_gets_a_row_and_we_are_told(self):
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "l@gmail.com")])})
        self.assertEqual(self._run(book), [{"office": "luke", "status": "recorded"}])
        self.assertEqual(book.tabs[CA.MAIL_TAB].rows[-1][:2], ["luke", "l@gmail.com"])
        self.assertIn("recorded", book.tabs[P.FAULTS_TAB].cells[(2, P.F_POSTED + 1)])
        self.assertEqual(len(self.told), 1)
        self.assertIn("l@gmail.com", self.told[0])

    def test_a_second_setup_replaces_the_address(self):
        mail = Sheet([CA.MAIL_HEADER, ["luke", "old@gmail.com", "", ""]])
        updates = []
        mail.update = lambda rng, vals: updates.append((rng, vals))
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "new@gmail.com")]),
                     CA.MAIL_TAB: mail})
        self._run(book)
        self.assertEqual(updates[0][0], "A2:D2")
        self.assertEqual(updates[0][1][0][:2], ["luke", "new@gmail.com"])
        self.assertEqual(len(mail.rows), 2, "no second row")

    def test_a_dry_run_writes_and_tells_nothing(self):
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "l@gmail.com")])})
        self._run(book, send=False)
        self.assertNotIn(CA.MAIL_TAB, book.tabs)
        self.assertEqual(self.told, [])

    def test_the_poster_leaves_forwards_for_record_forwards(self):
        self.assertIn('"probe-code-forward"', inspect.getsource(P.notify_faults))


if __name__ == "__main__":
    unittest.main()
