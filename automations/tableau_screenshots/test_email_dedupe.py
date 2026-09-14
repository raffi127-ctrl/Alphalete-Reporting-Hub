"""An email org must not be mailed the same tracker twice in a day.

2026-09-14: Joseph Logan's inbox held all 8 country trackers TWICE plus the B2B
Box follow-up twice. The channel path has always skipped what today's thread
already carries; the email path had no equivalent, so every run mailed the whole
set again — and the run that did it was the Box CATCH-UP, whose entire job is to
deliver the one board that lands late.

Megan: "why did he also get this many emails for trackers..."

A thread is a container — eleven replies under one header still read as one
thing. An inbox is not, which is the reason this module mails one message a day
in the first place.

    python -m unittest automations.tableau_screenshots.test_email_dedupe
"""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import unittest
from pathlib import Path

from automations.tableau_screenshots import slack_post as sp

DAY = dt.date(2026, 9, 14)
ORG = "joseph"


def _spec(pid, title=None):
    return {"id": pid, "title": title or pid.replace("_", " ").title()}


class EmailDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = sp._emailed_path
        sp._emailed_path = lambda: self.tmp / "_emailed.json"

    def tearDown(self):
        sp._emailed_path = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_nothing_recorded_means_nothing_deduped(self):
        self.assertEqual(sp._emailed_today(ORG, DAY), set())

    def test_recording_then_reading_round_trips(self):
        sp._record_emailed(ORG, DAY, ["att_country", "nds"])
        self.assertEqual(sp._emailed_today(ORG, DAY), {"att_country", "nds"})

    def test_a_second_record_adds_rather_than_replaces(self):
        """The catch-up run must not erase the morning's set — otherwise the NEXT
        run would happily re-send everything again."""
        sp._record_emailed(ORG, DAY, ["att_country"])
        sp._record_emailed(ORG, DAY, ["b2b_box"])
        self.assertEqual(sp._emailed_today(ORG, DAY), {"att_country", "b2b_box"})

    def test_days_are_separate(self):
        """Tomorrow's run sends the same boards again — that is the product."""
        sp._record_emailed(ORG, DAY, ["att_country"])
        self.assertEqual(sp._emailed_today(ORG, DAY + dt.timedelta(days=1)),
                         set())

    def test_orgs_are_separate(self):
        sp._record_emailed(ORG, DAY, ["att_country"])
        self.assertEqual(sp._emailed_today("someone_else", DAY), set())

    def test_old_days_are_pruned(self):
        sp._record_emailed(ORG, DAY - dt.timedelta(days=30), ["ancient"])
        sp._record_emailed(ORG, DAY, ["att_country"])
        self.assertEqual(sp._emailed_today(ORG, DAY - dt.timedelta(days=30)),
                         set(), "a month-old day should have been pruned")
        self.assertEqual(sp._emailed_today(ORG, DAY), {"att_country"})

    def test_an_unreadable_state_file_does_not_block_a_send(self):
        """Failing to dedupe is a duplicate; failing OPEN the other way is an
        owner who gets no trackers at all. The first is recoverable."""
        (self.tmp / "_emailed.json").write_text("{ this is not json")
        self.assertEqual(sp._emailed_today(ORG, DAY), set())


class TheCatchUpRunSendsOnlyTheLateBoard(unittest.TestCase):
    """The exact 2026-09-14 shape: morning run mails 8, then the Box catch-up
    runs carrying all 9 captures and must mail ONE."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved_path = sp._emailed_path
        sp._emailed_path = lambda: self.tmp / "_emailed.json"
        self.sent = []

        self._saved_mail = None
        import automations.shared.report_email as _mail
        self._mail = _mail
        self._saved_mail = _mail.send_boards
        def _fake(**kw):
            self.sent.append([lbl for lbl, *_r in kw["blocks"]])
            return {"ok": True}
        _mail.send_boards = _fake

        self._saved_emails_for = sp.emails_for
        sp.emails_for = lambda org: ["joseph@loganlegacygroup.com"]

    def tearDown(self):
        sp._emailed_path = self._saved_path
        self._mail.send_boards = self._saved_mail
        sp.emails_for = self._saved_emails_for
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _captures(self, ids):
        return [(_spec(i), self.tmp / f"{i}.png") for i in ids]

    def test_morning_then_catchup(self):
        morning = ["att_country", "att_country_int", "nds", "b2b_att",
                   "b2b_att_cru", "b2b_d2d", "att_quantum", "vz_ftr"]
        res = sp._email_all(self._captures(morning), [], DAY, org=ORG)
        self.assertTrue(res["ok"])
        self.assertEqual(len(self.sent[0]), 8, "the morning set goes in full")

        # The catch-up carries the whole day's captures, Box included.
        res2 = sp._email_all(self._captures(morning + ["b2b_box"]), [], DAY,
                             org=ORG)
        self.assertTrue(res2["ok"])
        self.assertEqual(len(self.sent), 2, "it still sends — Box is new")
        self.assertEqual(len(self.sent[1]), 1,
                         "and it sends ONLY Box, not all nine again")

    def test_a_third_identical_run_sends_nothing(self):
        ids = ["att_country", "nds"]
        sp._email_all(self._captures(ids), [], DAY, org=ORG)
        res = sp._email_all(self._captures(ids), [], DAY, org=ORG)
        self.assertTrue(res["ok"], "a no-op is not a failure")
        self.assertTrue(res.get("skipped"))
        self.assertEqual(len(self.sent), 1, "no second mail")

    def test_resend_is_still_possible_on_purpose(self):
        """--replace / updated=True means 'this REPLACES what went earlier'."""
        ids = ["att_country", "nds"]
        sp._email_all(self._captures(ids), [], DAY, org=ORG)
        sp._email_all(self._captures(ids), [], DAY, org=ORG, resend=True)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(self.sent[1]), 2, "a deliberate resend is whole")

    def test_a_failed_send_is_not_recorded(self):
        """Otherwise one SMTP hiccup costs the owner that board all day."""
        self._mail.send_boards = lambda **kw: {"ok": False, "reason": "smtp"}
        sp._email_all(self._captures(["att_country"]), [], DAY, org=ORG)
        self.assertEqual(sp._emailed_today(ORG, DAY), set())


if __name__ == "__main__":
    unittest.main()
