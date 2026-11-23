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
        with mock.patch.object(drive, "to_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster", return_value=1):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.ALREADY)
        self.assertIn("stale", out["Alena Guerrero"]["why"])

    def test_somebody_genuinely_pending_is_left_alone(self):
        out = self._out(["Jade Starkes"])
        with mock.patch.object(drive, "to_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster", return_value=0):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Jade Starkes"]["need"], drive.COMPLETE)

    def test_an_unreadable_active_tab_clears_nobody(self):
        """An unreadable tab says nothing about anybody. Going quietly back
        to the old behaviour is how Alena gets typed over next time."""
        said = []
        out = self._out(["Alena Guerrero"])
        with mock.patch.object(drive, "to_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=False):
            drive._rule_out_the_active(None, out, log=said.append)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.COMPLETE)
        self.assertIn("nobody was ruled out", " ".join(said))

    def test_a_search_that_will_not_run_clears_only_that_person(self):
        out = self._out(["Alena Guerrero", "Jade Starkes"])
        answers = {"Guerrero": None, "Starkes": 1}
        with mock.patch.object(drive, "to_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster",
                               side_effect=lambda _p, sur, giv, log=None: answers[sur]):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(out["Alena Guerrero"]["need"], drive.COMPLETE)
        self.assertEqual(out["Jade Starkes"]["need"], drive.ALREADY)

    def test_the_active_tab_is_opened_once_not_per_person(self):
        """The per-person tab click is the cost the Pending-first order was
        written to avoid; this must not reintroduce it."""
        out = self._out(["A One", "B Two", "C Three"])
        with mock.patch.object(drive, "to_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=True) as tab, \
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


class GettingBackToTheRosterFirst(unittest.TestCase):
    """The Pending lookup OPENS the person it finds, so this runs on an
    employee record unless it navigates back. The first cut did not, said
    "no 'Active' tab on this page", and cleared nobody -- right answer,
    wrong reason, and nobody would ever have been ruled out."""

    def test_the_roster_is_reached_before_the_tab_is_asked_for(self):
        order = []
        out = {"A One": {"need": drive.COMPLETE, "why": "on Pending", "id": "1"}}
        with mock.patch.object(drive, "to_roster",
                               side_effect=lambda *_a, **_k: order.append("roster") or True), \
             mock.patch.object(drive, "open_roster_tab",
                               side_effect=lambda *_a, **_k: order.append("tab") or True), \
             mock.patch.object(drive, "search_roster", return_value=0):
            drive._rule_out_the_active(None, out, log=lambda *_a: None)
        self.assertEqual(order, ["roster", "tab"])

    def test_a_roster_we_cannot_reach_clears_nobody(self):
        said = []
        out = {"A One": {"need": drive.COMPLETE, "why": "on Pending", "id": "1"}}
        with mock.patch.object(drive, "to_roster", return_value=False), \
             mock.patch.object(drive, "open_roster_tab") as tab:
            drive._rule_out_the_active(None, out, log=said.append)
        tab.assert_not_called()
        self.assertEqual(out["A One"]["need"], drive.COMPLETE)
        self.assertIn("nobody was ruled out", " ".join(said))


class TheLookupIsGivenSomethingToSearchOn(unittest.TestCase):
    """__ansOpen is handed the person dict and searches by `find`.

    2026-11-23: the supervised run always passed it and the batch pass never
    did, so one found people on Pending and the other reported all 26 as
    needing a person. Filled in inside triage so the next caller cannot
    forget it.
    """

    class _Page:
        url = "https://apex.example/roster"

        def __init__(self):
            self.asked = []

        def evaluate(self, js, arg=None):
            if "__ansOpen" in js:
                self.asked.append(dict(arg or {}))
                return ""
            return True

        def wait_for_timeout(self, _ms):
            pass

    def _triage(self, people):
        page = self._Page()
        with mock.patch.object(drive, "wait_for_roster", return_value=True), \
             mock.patch.object(drive, "open_roster_tab", return_value=True), \
             mock.patch.object(drive, "search_roster", return_value=0), \
             mock.patch.object(drive, "on_roster", return_value=True):
            drive.triage(page, people, log=lambda *_a: None)
        return page.asked

    def test_a_name_only_person_still_gets_a_find(self):
        asked = self._triage([{"name": "Alexis Justice"}])
        self.assertEqual(asked[0]["find"], "Justice")

    def test_a_caller_that_supplies_find_keeps_theirs(self):
        """The supervised run sets it deliberately; this must not override."""
        asked = self._triage([{"name": "Alexis Justice", "find": "McCrobie"}])
        self.assertEqual(asked[0]["find"], "McCrobie")

    def test_the_rest_of_the_dict_is_passed_through(self):
        asked = self._triage([{"name": "A One", "pages": ["x"]}])
        self.assertEqual(asked[0]["pages"], ["x"])
