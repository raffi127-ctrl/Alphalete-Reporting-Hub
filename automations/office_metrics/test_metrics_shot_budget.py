"""The capture of all offices has to leave time for this office to post.

2026-11-03 to 11-09: the first office on each Lucy shot its own picture, kept
shooting everyone else's and hit the runner's 20-minute kill before posting it.

  python -m automations.office_metrics.test_metrics_shot_budget
"""
from __future__ import annotations

import contextlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from automations.office_metrics import metrics_shot as MS


@contextlib.contextmanager
def _session(**_kw):
    yield object()


class OwnFirst(unittest.TestCase):
    def test_moves_own_office_to_the_front_without_duplicating(self):
        self.assertEqual(MS.own_first("c", ["a", "b", "C"]), ["c", "a", "b"])

    def test_office_not_in_the_list_still_goes_first(self):
        self.assertEqual(MS.own_first("z", ["a", "b"]), ["z", "a", "b"])


class Budget(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.shot = []

        def capture_page(_page, spec, out_dir, verbose=True):
            self.shot.append(spec["title"])
            p = Path(out_dir) / "raw.png"
            p.write_bytes(b"x")
            return p

        fake_cap = types.SimpleNamespace(capture_page=capture_page)
        pkg = types.ModuleType("automations.tableau_screenshots")
        pkg.capture = fake_cap
        tp = types.ModuleType("automations.shared.tableau_patchright")
        tp.tableau_session = _session
        for p in (mock.patch.dict(sys.modules, {
                      "automations.tableau_screenshots": pkg,
                      "automations.tableau_screenshots.capture": fake_cap,
                      "automations.shared.tableau_patchright": tp}),
                  mock.patch.object(MS, "_cache_dir", return_value=self.dir)):
            p.start()
            self.addCleanup(p.stop)

    def _run(self, owners, clock, budget=720):
        with mock.patch.object(MS.time, "monotonic", side_effect=clock):
            return MS.capture_all(owners, filter_field="Owner Name", verbose=False,
                                  budget_s=budget)

    def test_stops_starting_shots_when_the_budget_is_gone(self):
        # start, a is on time, b is past the budget
        got = self._run(["a", "b", "c"], [0, 10, 721])
        self.assertEqual(list(got), ["a"])
        self.assertEqual(self.shot, ["Metrics — a"])

    def test_next_office_resumes_off_the_cache(self):
        self._run(["a", "b"], [0, 10, 721])
        got = self._run(["b", "a"], [0, 10])
        self.assertEqual(sorted(got), ["a", "b"])
        self.assertEqual(self.shot, ["Metrics — a", "Metrics — b"])

    def test_cached_offices_cost_nothing_even_past_the_budget(self):
        self._run(["a"], [0, 10])
        got = self._run(["a"], [0])
        self.assertEqual(list(got), ["a"])
        self.assertEqual(self.shot, ["Metrics — a"])

    def test_no_budget_shoots_everyone(self):
        with mock.patch.object(MS.time, "monotonic", return_value=99999):
            got = MS.capture_all(["a", "b"], filter_field="Owner Name", verbose=False)
        self.assertEqual(sorted(got), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
