"""Offline checks for the B2B roster read (no Tableau, no Sheet, no Slack).

    python -m unittest automations.new_owners.test_cap_roster
"""
import tempfile
import unittest
from pathlib import Path

from automations.new_owners import cap_roster as cr

# The CB-Owner Metrics export as the 2026-10-12 probe saw it: no owner header.
HEADER = "\t\tChurn Rate (0-30 days)\tActivation Rate (31-60 days)\n"


def _file(body: str) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "cb_owner_metrics.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


class TeamListOwners(unittest.TestCase):
    def test_reads_owner_beside_team(self):
        p = _file("Carlos's Team\tCarlos Hidalgo\t8.1%\t72.6%\n"
                  "Carlos's Team\tJoey Ramirez\t2.9%\t79.3%\n"
                  "Carlos's Team\tGrand Total\t5.0%\t75.0%\n")
        got = cr._team_list_owners(p, "Carlos's Team")
        self.assertEqual(sorted(got.values()), ["Carlos Hidalgo", "Joey Ramirez"])

    def test_curly_apostrophe_matches(self):
        p = _file("Carlos’s Team\tJoey Ramirez\t2.9%\t79.3%\n")
        self.assertEqual(len(cr._team_list_owners(p, "Carlos's Team")), 1)

    def test_filter_not_applied_fails(self):
        p = _file("Carlos's Team\tJoey Ramirez\t2.9%\t79.3%\n"
                  "Luis's Team\tSomeone Else\t1.0%\t70.0%\n")
        with self.assertRaises(RuntimeError):
            cr._team_list_owners(p, "Carlos's Team")

    def test_empty_export_fails_not_zero(self):
        with self.assertRaises(RuntimeError):
            cr._team_list_owners(_file(""), "Carlos's Team")


class ScanOrder(unittest.TestCase):
    def test_nds_runs_before_b2b(self):
        seen = []
        orig = cr.roster_for
        cr.roster_for = lambda c, page, **kw: seen.append(c) or {}
        try:
            cr.scan(None, ["Eveliz", "Khalil", "Luis", "Jairo"], logfn=lambda *_: None)
        finally:
            cr.roster_for = orig
        self.assertEqual(seen, ["Khalil", "Jairo", "Eveliz", "Luis"])


if __name__ == "__main__":
    unittest.main()
