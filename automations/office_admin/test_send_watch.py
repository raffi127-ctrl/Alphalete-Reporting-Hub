"""A send that finished should say so.

Megan, 2026-11-25, after the first real drug order: "nothing says a send
worked... an admin has no watcher -- they press Send and then keep reloading
a row."
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.office_admin import config as C, send_watch as SW


def _row(action=C.SEND_DRUG, status=C.AT_OFFICE, office="raf",
         people=(("Rae", "Linwood"), ("Cal", "Bramley")), result=""):
    return {"Request ID": "r1", "Action": action, "Status": status,
            "Office Key": office, "Result": result, "_row": 2,
            "Details": json.dumps({"people": [
                {"first_name": f, "last_name": l} for f, l in people]})}


class WhichRowsAreWatched(unittest.TestCase):

    def test_an_open_send_is_picked_up(self):
        self.assertEqual(len(SW.open_sends([_row()])), 1)

    def test_a_finished_one_is_not(self):
        """Writing the verdict moves the row off 'at office computer', so the
        pass that notifies is the pass that resolves it -- which is why no
        marker file is needed."""
        self.assertEqual(SW.open_sends([_row(status=C.DONE)]), [])

    def test_both_kinds_are_watched(self):
        self.assertEqual(len(SW.open_sends([_row(action=C.SEND_BGC),
                                            _row(action=C.SEND_DRUG)])), 2)

    def test_another_action_is_not(self):
        self.assertEqual(SW.open_sends([_row(action=C.APEX_SEND)]), [])

    def test_one_office_can_be_asked_for(self):
        rows = [_row(office="raf"), _row(office="omar")]
        self.assertEqual(len(SW.open_sends(rows, "omar")), 1)


class WhatTheDmSays(unittest.TestCase):

    def test_sent_names_who_went(self):
        txt = SW.message(_row(), {"status": "sent",
                                  "sent": ["Rae Linwood", "Cal Bramley"]})
        self.assertIn("Drug tests sent", txt)
        self.assertIn("Rae Linwood", txt)

    def test_a_background_check_says_so(self):
        txt = SW.message(_row(action=C.SEND_BGC), {"status": "sent",
                                                   "sent": ["Ada Fournier"]})
        self.assertIn("Background checks sent", txt)

    def test_failed_says_nobody_was_invited(self):
        txt = SW.message(_row(), {"status": "error", "failed": ["Rae Linwood"],
                                  "error": "Screening Package: found 2"})
        self.assertIn("did not send", txt)
        self.assertIn("Nobody was invited", txt)
        self.assertIn("Screening Package", txt)

    def test_unconfirmed_is_its_own_message(self):
        """The most important distinction there is: it MAY have gone out, so
        pressing again could invite the same people twice."""
        txt = SW.message(_row(), {"status": "error",
                                  "unconfirmed": ["Rae Linwood"]})
        self.assertIn("not sure these went out", txt)
        self.assertIn("twice", txt)
        self.assertNotIn("Nobody was invited", txt)

    def test_a_dry_run_is_not_reported_as_sent(self):
        txt = SW.message(_row(), {"status": "dry_run",
                                  "would_send": ["Rae Linwood"]})
        self.assertIn("test run", txt)
        self.assertIn("Nothing was sent", txt)


class TheRun(unittest.TestCase):

    def _go(self, after, send=False):
        said = []
        with mock.patch("automations.office_admin.sheets.requests_tab"), \
             mock.patch("automations.office_admin.sheets.read_requests",
                        return_value=[_row()]), \
             mock.patch("automations.office_admin.actions.refresh_send",
                        return_value=after), \
             mock.patch("automations.icd_alerts.post.dm_office_people",
                        return_value=["U1"]) as dm:
            n = SW.run(send=send, log=said.append)
        return n, " ".join(said), dm

    def test_still_waiting_notifies_nobody(self):
        n, said, dm = self._go(_row(), send=True)
        self.assertEqual(n, 0)
        dm.assert_not_called()
        self.assertIn("still waiting", said)

    def test_a_verdict_dms_the_office(self):
        done = _row(status=C.DONE,
                    result=json.dumps({"status": "sent",
                                       "sent": ["Rae Linwood"]}))
        n, said, dm = self._go(done, send=True)
        self.assertEqual(n, 1)
        dm.assert_called_once()
        self.assertIn("Drug tests sent", dm.call_args[0][1])

    def test_dry_run_sends_nothing(self):
        done = _row(status=C.DONE, result=json.dumps({"status": "sent"}))
        n, said, dm = self._go(done, send=False)
        self.assertEqual(n, 1)
        dm.assert_not_called()
        self.assertIn("would DM", said)

    def test_a_dm_that_fails_does_not_hide_the_verdict(self):
        """The verdict is already on the row. A DM we could not deliver must
        not make the run look like the send is still out."""
        done = _row(status=C.FAILED, result=json.dumps({"status": "error"}))
        said = []
        with mock.patch("automations.office_admin.sheets.requests_tab"), \
             mock.patch("automations.office_admin.sheets.read_requests",
                        return_value=[_row()]), \
             mock.patch("automations.office_admin.actions.refresh_send",
                        return_value=done), \
             mock.patch("automations.icd_alerts.post.dm_office_people",
                        side_effect=RuntimeError("slack down")):
            n = SW.run(send=True, log=said.append)
        self.assertEqual(n, 1)
        self.assertIn("the verdict IS on the row", " ".join(said))


if __name__ == "__main__":
    unittest.main()
