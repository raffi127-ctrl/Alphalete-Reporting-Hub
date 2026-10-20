"""No OBCL tab + nobody in the box = a quiet week, not a failure (Megan
2026-10-20: no classroom the week of 10/12, the team was in Cancun).

    python -m unittest automations.new_starts_box.test_quiet_week
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.new_starts_box import run as R


class _WS:
    title = "Sales Board WE 10.18"

    def get_all_values(self):
        return []


class _Book:
    def worksheet(self, _t):
        return _WS()


class _GC:
    def open_by_key(self, _k):
        return _Book()


class QuietWeek(unittest.TestCase):

    def _run(self, people, lnotes):
        counts = {"people": people, "filled": 0, "replaced": 0, "kept": 0,
                  "blank": 0, "orphans": 0}
        with mock.patch("automations.recruiting_report.fill._client",
                        return_value=_GC()), \
                mock.patch.object(R.S, "open_tab", return_value=_WS()), \
                mock.patch.object(R.S, "trainers", return_value=([], [])), \
                mock.patch.object(R.S, "locations", return_value=([], lnotes)), \
                mock.patch.object(R.F, "prior_week_teams", return_value={}), \
                mock.patch.object(R.F, "plan", return_value=([], [], counts)), \
                mock.patch.object(R.X, "find_box", return_value=(5, {"Trainers": 1, "Location": 2, "Team": 3})), \
                mock.patch.object(R.X, "a1", return_value="A5"), \
                mock.patch.object(R.F, "apply", return_value=0):
            return R.main(["--day", "2026-10-14"])

    def test_no_tab_and_empty_box_is_quiet(self):
        self.assertEqual(self._run(0, ["MISSING: no 'D2D OBCL 10.12' tab in 'x' -- Location left blank"]), 0)

    def test_missing_tab_with_people_still_fails(self):
        self.assertEqual(self._run(3, ["MISSING: no 'D2D OBCL 10.12' tab in 'x' -- Location left blank"]), 1)

    def test_empty_box_with_a_tab_still_fails(self):
        self.assertEqual(self._run(0, []), 1)


if __name__ == "__main__":
    unittest.main()
