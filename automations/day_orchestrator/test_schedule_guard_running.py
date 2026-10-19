"""The nightly schedule guard leaves RUNNING jobs alone (2026-10-19: its 02:45
reload killed Lucy 2's 01:10 recruiting chain mid-run on slow nights).

    python -m unittest automations.day_orchestrator.test_schedule_guard_running
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.day_orchestrator import install_agent
from automations.day_orchestrator import schedule_guard as G

LIST = ("PID\tStatus\tLabel\n"
        "4242\t0\tcom.alphalete.recruiting-chain-1am\n"
        "-\t0\tcom.alphalete.ad-sales-board\n"
        "-\t0\tcom.apple.something\n")


class _Run:
    stdout = LIST


class RunningJobs(unittest.TestCase):

    def test_parses_pids(self):
        with mock.patch.object(G.subprocess, "run", return_value=_Run()):
            self.assertEqual(G._launchctl_list(), {
                "com.alphalete.recruiting-chain-1am": 4242,
                "com.alphalete.ad-sales-board": None})
            self.assertEqual(G.running_labels(),
                             {"com.alphalete.recruiting-chain-1am"})

    def test_running_job_not_reloaded(self):
        jobs = [("com.alphalete.recruiting-chain-1am", "recruiting-chain-1am", []),
                ("com.alphalete.ad-sales-board", "ad-sales-board", [])]
        reloaded = []
        with mock.patch.object(G, "_timed_jobs", return_value=jobs), \
                mock.patch.object(G, "running_labels",
                                  return_value={"com.alphalete.recruiting-chain-1am"}), \
                mock.patch.object(install_agent, "install",
                                  side_effect=lambda n: reloaded.append(n) or (True, "ok")), \
                mock.patch("automations.day_orchestrator.hub_coverage.sync",
                           side_effect=RuntimeError("skip")), \
                mock.patch("sys.argv", ["schedule_guard"]):
            rc = G.main()
        self.assertEqual(reloaded, ["ad-sales-board"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
