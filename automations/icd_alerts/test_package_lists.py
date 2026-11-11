"""The two lists that decide what an office computer holds stay in step.

`package.AGENT_FILES` is what we SAY ships. `agent_files.txt` is what an office
actually downloads (install.sh, update.sh, selfupdate). On 2026-11-08 nineteen
new-starts -> Apex files went into the first and not the second, and for three
days the code read as shipped while no office had it.

    python -m unittest automations.icd_alerts.test_package_lists
"""
import unittest
from pathlib import Path

from automations.icd_alerts import package

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _listed():
    return {l.strip() for l in (HERE / "agent_files.txt").read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")}


class ApexWeekShipsWholeOrNotAtAll(unittest.TestCase):

    def test_the_apex_files_are_in_both_lists_or_in_neither(self):
        apex = set(package.APEX_WEEK_FILES)
        in_pkg = apex & set(package.AGENT_FILES)
        in_txt = apex & _listed()
        self.assertEqual(in_pkg, in_txt,
                         "new starts -> Apex is half shipped again: these are "
                         "in one list and not the other")
        self.assertIn(len(in_txt), (0, len(apex)),
                      "only some of the Apex files are listed -- the job "
                      "imports all of them")

    def test_every_apex_file_named_is_a_real_file(self):
        gone = [f for f in package.APEX_WEEK_FILES if not (REPO / f).exists()]
        self.assertEqual(gone, [], "APEX_WEEK_FILES names a file that moved")

    def test_an_office_machine_refuses_apex_rather_than_crashing(self):
        """Until those files ship, the job's imports fail on an office Mac.
        That has to come back as an answer, never as a dead sweep."""
        src = (HERE / "office_jobs.py").read_text()
        body = src[src.index("def work("):src.index("def run_once(")]
        self.assertIn("try:", body)
        self.assertIn('res = {"status": "error"', body)


if __name__ == "__main__":
    unittest.main()
