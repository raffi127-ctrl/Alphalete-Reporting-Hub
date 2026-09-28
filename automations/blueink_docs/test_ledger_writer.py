"""A failed 'Blue Ink Log' write must never stop the batch.

2026-09-28: the Monday send got 14 of 55 out, then one Sheets 429 on the
per-person log write (the shared alphaletereporting@ read quota) raised out of
the send loop and 41 new starts got nothing. The packet had already gone --
losing its log line is not worth losing everybody after it.

    python -m unittest automations.blueink_docs.test_ledger_writer
"""
from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.blueink_docs import ledger, run
from automations.blueink_docs.roster import NewStart


def _person(first, last):
    return NewStart(first=first, last=last, email=f"{first.lower()}@example.com",
                    phone="", final_status="", bg_status="", friday="",
                    trainer="", tab="D2D OBCL 9.28", row=3, section=1)


class FlakyTab:
    """The ledger tab. `fail` = how many append calls raise before one works."""

    def __init__(self, fail):
        self.fail = fail
        self.written = []

    def append_rows(self, rows, value_input_option=None):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("APIError: [429]: Quota exceeded for quota "
                               "metric 'Read requests'")
        self.written.extend(rows)


class FakeWorkbook:
    def __init__(self, tab):
        self.tab = tab
        self.lookups = 0

    def worksheet(self, title):
        self.lookups += 1
        return self.tab


def _run_batch(people, workbook):
    """_send_via_ui with the browser and the sheet tint stubbed out."""
    sent_ok = lambda page, person, template, really_send: SimpleNamespace(
        status="sent", bundle_id="B-" + person.first)
    fake_p = mock.MagicMock()
    with mock.patch.object(run.bi_session, "_sync_api",
                           return_value=lambda: contextlib.nullcontext(fake_p)), \
         mock.patch.object(run.ui_send, "open_browser",
                           return_value=(mock.MagicMock(), mock.MagicMock())), \
         mock.patch.object(run, "_send_one_with_retry", side_effect=sent_ok), \
         mock.patch.object(run.mark, "highlight", return_value=0), \
         mock.patch.object(run.ledger, "Writer",
                           lambda wb, _W=ledger.Writer: _W(wb, final_wait=0)):
        return run._send_via_ui(workbook, mock.MagicMock(title="D2D OBCL 9.28"),
                                people, really_send=True)


class FailedLogWriteDoesNotAbort(unittest.TestCase):
    PEOPLE = [_person("Alexa", "Diaz"), _person("Jayla", "Ceasor"),
              _person("Michael", "Anderson")]

    def test_one_failed_write_still_sends_everyone_and_logs_them_later(self):
        tab = FlakyTab(fail=1)                   # the 9/28 shape: one bad write
        failures, sent, _, names, _, unlogged = _run_batch(
            self.PEOPLE, FakeWorkbook(tab))
        self.assertEqual(sent, 3)                # nobody after it was dropped
        self.assertEqual(failures, 0)
        self.assertEqual(names, ["Alexa Diaz", "Jayla Ceasor", "Michael Anderson"])
        # The held row went up with the next person's -- nothing lost.
        self.assertEqual([r[ledger.COL_NAME] for r in tab.written], names)
        self.assertEqual(unlogged, [])

    def test_writes_that_never_recover_are_named_not_raised(self):
        tab = FlakyTab(fail=99)
        failures, sent, _, _, _, unlogged = _run_batch(
            self.PEOPLE, FakeWorkbook(tab))
        self.assertEqual(sent, 3)
        self.assertEqual(unlogged, ["Alexa Diaz", "Jayla Ceasor",
                                    "Michael Anderson"])

    def test_the_tab_is_looked_up_once_per_run_not_per_person(self):
        wb = FakeWorkbook(FlakyTab(fail=0))
        _run_batch(self.PEOPLE, wb)
        self.assertEqual(wb.lookups, 1)


class WriterFinish(unittest.TestCase):
    def test_final_retry_waits_then_writes(self):
        tab = FlakyTab(fail=2)
        w = ledger.Writer(FakeWorkbook(tab), final_wait=60)
        self.assertFalse(w.add(ledger.row_for(_person("Leo", "Fan"), "B-1", "sent")))
        waits = []
        self.assertEqual(w.finish(sleep=waits.append), [])
        self.assertEqual(waits, [60])
        self.assertEqual(len(tab.written), 1)


if __name__ == "__main__":
    unittest.main()
