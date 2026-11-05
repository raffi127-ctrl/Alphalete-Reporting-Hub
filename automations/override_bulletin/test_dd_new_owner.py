"""A new owner earning DD reaches their leaders' lists; the exceptions never do.

    python -m unittest automations.override_bulletin.test_dd_new_owner
"""
from __future__ import annotations

import unittest

from automations.override_bulletin import dd_new_owner as N

DD = [
    ["ICD", "Active ICD", "Campaign", "ORG", "Total DD", "11.1.26", "10.25.26"],
    ["Omar Mohamad", "YES", "Fiber", "Raf", "$228.00", "$228.00", ""],
    ["Jacob Dover", "YES", "Fiber", "Salik", "$9.00", "$22,429.00", ""],
    ["Haytham Nagi", "YES", "Fiber", "Salik", "$9.00", "$24,983.00", ""],
    ["Quiet Owner", "YES", "Fiber", "Raf", "$0.00", "$0.00", ""],
    ["Cody Cannon", "YES", "Fiber", "Raf", "$9.00", "$5,918.00", ""],
    ["Karrington Moody", "NO", "NDS", "Raf", "$0.00", "", ""],
    ["Old Owner", "NO", "NDS", "Raf", "$0.00", "", ""],
    ["Returning", "NO", "NDS", "Raf", "$0.00", "", ""],
    ["Total - Raf", "", "", "", "$1.00", "$1.00", ""],
    [""],
    ["ICD (Special Cases)", "", "", "", "", "", ""],
    ["Karrington Moody", "", "", "Colten", "$1.00", "$15,158.00", ""],
]
TREE = [
    ["PODIUM LEADERS"], ["Leader", "Location", "Minus orgs", "Expected ICDs"],
    ["Rafael Hidalgo", "TX", "Carlos Hidalgo", "38"],
    ["Salik Mallick", "MI", "", "3"],
    ["Hammad Haque", "MI", "", "2"],
    [""],
    ["PODIUM ORG LISTS"], ["Leader", "ICD"],
    ["Salik Mallick", "Haytham Nagi"],
    ["Hammad Haque", "Haytham Nagi"],
]
ORG = [
    ["Generation", "1", "2", "3", "4"],
    ["Rafael Hidalgo", "Salik Mallick", "Hammad Haque", "Jacob Dover", ""],
    ["", "", "", "Haytham Nagi", "New Hire"],
    ["", "", "", "Omar Mohamad", ""],
    ["", "", "", "Returning", ""],
    ["", "", "", "Quiet Owner", ""],
    ["", "Cody Cannon (1/2)", "", "", ""],
    ["", "Karrington Moody", "", "", ""],
]
ADOPT = {"karrington moody"}


def norm(s):
    return s.strip().lower()


class ListsTest(unittest.TestCase):
    def setUp(self):
        self.plan = N.plan_lists(DD, TREE, ORG, ADOPT, {})
        self.names = {p["name"] for p in self.plan}

    def test_new_earner_goes_on_every_leader_above(self):
        omar = next(p for p in self.plan if p["name"] == "Omar Mohamad")
        self.assertEqual(omar["add_to"], ["Salik Mallick", "Hammad Haque"])
        self.assertEqual(omar["amount"], 228.0)

    def test_dover_stays_off(self):
        self.assertNotIn("Jacob Dover", self.names)

    def test_already_listed_zero_split_and_adoption_stay_off(self):
        for n in ("Haytham Nagi", "Quiet Owner", "Cody Cannon", "Karrington Moody"):
            self.assertNotIn(n, self.names)

    def test_minus_leader_never_gets_a_list(self):
        for p in self.plan:
            self.assertNotIn("Rafael Hidalgo", p["add_to"])


class PullTest(unittest.TestCase):
    def _plan(self, pull):
        return N.plan_pull(DD, ORG, ADOPT, {}, pull, norm)

    def test_no_row_on_tree_gets_a_row_in_the_right_org(self):
        p = self._plan({"new hire": 500.0})
        self.assertEqual([(a["name"], a["org"]) for a in p["insert"]],
                         [("New Hire", "Salik")])

    def test_inactive_on_tree_is_activated(self):
        p = self._plan({"returning": 100.0})
        self.assertEqual([a["name"] for a in p["activate"]], ["Returning"])

    def test_inactive_off_tree_stays_inactive(self):
        p = self._plan({"old owner": 100.0})
        self.assertEqual(p, {"activate": [], "insert": [], "unplaced": []})

    def test_unknown_earner_is_reported_not_written(self):
        p = self._plan({"stranger": 100.0})
        self.assertEqual(p["unplaced"], [{"name": "stranger", "amount": 100.0}])
        self.assertEqual(p["insert"], [])

    def test_adoption_and_dover_and_negatives_do_nothing(self):
        p = self._plan({"karrington moody": 900.0, "jacob dover": 900.0,
                        "new hire": -5.0})
        self.assertEqual(p, {"activate": [], "insert": [], "unplaced": []})


class ApplyTest(unittest.TestCase):
    def test_rows_land_below_the_list_and_expected_goes_up(self):
        calls = []

        class WS:
            def update(self, values=None, range_name=None, **kw):
                calls.append(("rows", range_name, values))

            def update_cell(self, r, c, v):
                calls.append(("cell", r, c, v))

        plan = [{"name": "Omar Mohamad", "amount": 228.0,
                 "add_to": ["Salik Mallick", "Hammad Haque"]}]
        N._apply_lists(WS(), TREE, plan)
        self.assertEqual(calls[0][1], "A11:E12")
        self.assertEqual([r[:2] for r in calls[0][2]],
                         [["Salik Mallick", "Omar Mohamad"],
                          ["Hammad Haque", "Omar Mohamad"]])
        self.assertIn(("cell", 4, 4, 4), calls)
        self.assertIn(("cell", 5, 4, 3), calls)


if __name__ == "__main__":
    unittest.main()
