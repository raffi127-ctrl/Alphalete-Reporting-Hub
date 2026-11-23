"""On Pending is not the same as still pending.

2026-11-23: Alena Guerrero was ACTIVE in Apex. The Pending lookup found her
anyway and the triage said "on Pending", so a finished payroll record was
about to have all three of its tabs typed over again. Megan saw it on the
screen and stopped it; nothing in the code would have.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.apex_new_starts import drive


class RulingOutTheActive(unittest.TestCase):

    def _out(self, names, need=None):
        return {n: {"need": need or drive.COMPLETE, "why": "on Pending",
                    "id": "e%d" % i} for i, n in enumerate(names)}

    def test_somebody_on_active_is_not_completed_again(self):
        out = self._out(["Alena Guerrero"])
        with mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster", return_value=1):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.ALREADY)
        self.assertIn("stale", out["Alena Guerrero"]["why"])

    def test_somebody_genuinely_pending_is_left_alone(self):
        out = self._out(["Jade Starkes"])
        with mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster", return_value=0):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Jade Starkes"]["need"], drive.COMPLETE)

    def test_an_unreadable_active_tab_clears_nobody(self):
        """An unreadable tab says nothing about anybody. Going quietly back
        to the old behaviour is how Alena gets typed over next time."""
        said = []
        out = self._out(["Alena Guerrero"])
        with mock.patch.object(drive, "open_roster_tab", return_value=False):
            drive._rule_out_the_active(None, out, log=said.append)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.COMPLETE)
        self.assertIn("nobody was ruled out", " ".join(said))

    def test_a_search_that_will_not_run_clears_only_that_person(self):
        out = self._out(["Alena Guerrero", "Jade Starkes"])
        answers = {"Guerrero": None, "Starkes": 1}
        with mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster",
                               side_effect=lambda _p, sur, giv, log=None: answers[sur]):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.COMPLETE)
        self.assertEqual(out["Jade Starkes"]["need"], drive.ALREADY)

    def test_the_active_tab_is_opened_once_not_per_person(self):
        """The per-person tab click is the cost the Pending-first order was
        written to avoid; this must not reintroduce it."""
        out = self._out(["A One", "B Two", "C Three"])
        with mock.patch.object(drive, "open_roster_tab", return_value=True) as tab, \
             mock.patch.object(drive, "search_roster", return_value=0):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(tab.call_count, 1)

    def test_nobody_pending_means_the_tab_is_never_opened(self):
        out = self._out(["A One"], need=drive.ADD)
        with mock.patch.object(drive, "open_roster_tab") as tab:
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        tab.assert_not_called()

    def test_the_supervised_run_stops_instead_of_filling(self):
        import inspect
        from automations.apex_new_starts import supervised
        src = inspect.getsource(supervised.run)
        self.assertLess(src.index("drive.ALREADY"), src.index("drive.COMPLETE"),
                        "ALREADY must be checked before the complete path")
        self.assertIn("already Active and finished", src)


if __name__ == "__main__":
    unittest.main()
