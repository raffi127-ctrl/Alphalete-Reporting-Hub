"""An office that was switched ON and is now OFF is not a new office.

"no knocks destination is approved yet" reads identically for an office
waiting on Megan and one that was approved and has since been switched off.
That ambiguity cost Cyrus his whole board on 2026-09-15: a cadence change
re-wrote a column his machine owns, the relay read the disagreement as "they
are asking for somewhere different" and cleared his approval -- and the
message that followed was the one a brand new office produces. Nobody could
have told from the channel.

A new office is a nudge. A lost approval is a regression.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import post as P


class LosingAnApprovalIsLoud(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig = P.APPROVALS_PATH
        P.APPROVALS_PATH = self.tmp / "approvals.json"
        self.day = dt.date(2026, 9, 15)

    def tearDown(self):
        P.APPROVALS_PATH = self._orig

    def _run(self, knocks=None, channels=None, texts=None):
        with mock.patch.object(P, "approved_knocks", return_value=knocks or {}), \
                mock.patch.object(P, "approved_channels", return_value=channels or {}), \
                mock.patch.object(P, "approved_texts", return_value=texts or {}):
            return P.warn_lost_approvals(self.day, send=False,
                                         log=lambda *_: None)

    def test_a_brand_new_office_is_not_reported_as_lost(self):
        # It has never had an approval, so there is nothing to have lost.
        self.assertEqual(self._run(knocks={}), [])
        self.assertEqual(self._run(knocks={}), [])

    def test_an_office_that_loses_its_board_is_reported(self):
        self._run(knocks={"cyrus": [{"channel_id": "C1"}]})   # baseline
        out = self._run(knocks={})                            # switched off
        self.assertEqual(len(out), 1)
        self.assertIn("cyrus", out[0])
        self.assertIn("board", out[0])

    def test_it_is_reported_once_not_forever(self):
        self._run(knocks={"cyrus": [{"channel_id": "C1"}]})
        first = self._run(knocks={})
        second = self._run(knocks={})
        self.assertTrue(first)
        self.assertEqual(second, [],
                         "it keeps reporting a loss it already reported")

    def test_restoring_the_approval_goes_quiet(self):
        self._run(knocks={"cyrus": [{"channel_id": "C1"}]})
        self._run(knocks={})                                  # lost
        out = self._run(knocks={"cyrus": [{"channel_id": "C1"}]})
        self.assertEqual(out, [])

    def test_losing_only_texts_still_names_what_went(self):
        self._run(knocks={"carlos": [{"channel_id": "C1"}]},
                  texts={"carlos": [{"channel_id": "imessage:X"}]})
        out = self._run(knocks={"carlos": [{"channel_id": "C1"}]})
        self.assertEqual(len(out), 1)
        self.assertIn("texts", out[0])
        self.assertNotIn("board", out[0],
                         "it claims the board went too, which it did not")

    def test_one_office_losing_does_not_implicate_another(self):
        self._run(knocks={"cyrus": [{"channel_id": "C1"}],
                          "kash": [{"channel_id": "C2"}]})
        out = self._run(knocks={"kash": [{"channel_id": "C2"}]})
        self.assertEqual(len(out), 1)
        self.assertIn("cyrus", out[0])


class TheMachineFactsAreSaidWhenThereIsSomethingToSay(unittest.TestCase):
    """laptop_offices() and silent_machines() were written, tested, and wired
    to nothing -- so a machine going quiet was something Megan noticed by
    eye."""

    def test_nothing_to_report_says_nothing(self):
        with mock.patch.object(P, "laptop_offices", return_value=[]), \
                mock.patch.object(P, "silent_machines", return_value=[]):
            self.assertEqual(
                P.warn_machine_facts(send=False, log=lambda *_: None), [])

    def test_a_laptop_is_named(self):
        with mock.patch.object(P, "laptop_offices", return_value=[
                    {"office": "someone", "name": "MacBook Air"}]), \
                mock.patch.object(P, "silent_machines", return_value=[]):
            out = P.warn_machine_facts(send=False, log=lambda *_: None)
        self.assertTrue(any("MacBook Air" in l for l in out))

    def test_an_agent_too_old_to_answer_is_named_separately(self):
        with mock.patch.object(P, "laptop_offices", return_value=[]), \
                mock.patch.object(P, "silent_machines", return_value=[
                    {"office": "cyrus", "agent": "icd_alerts/2"}]):
            out = P.warn_machine_facts(send=False, log=lambda *_: None)
        joined = " ".join(out)
        self.assertIn("cyrus", joined)
        self.assertIn("icd_alerts/2", joined)
        self.assertNotIn("On a laptop", joined,
                         "an office we cannot ask is being called a laptop")

    def test_it_is_wired_into_the_poster(self):
        import inspect
        src = inspect.getsource(P.main)
        self.assertIn("warn_machine_facts", src)
        self.assertIn("warn_lost_approvals", src)


if __name__ == "__main__":
    unittest.main()
