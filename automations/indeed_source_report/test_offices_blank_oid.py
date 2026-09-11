"""A roster person with no office yet must never reach the office switcher.

  python -m unittest automations.indeed_source_report.test_offices_blank_oid

2026-09-11: Nicolas Lujan was added with oid "" (not None). The pull list let
"" through, the switch to office "" did nothing, and the Ad Sales Board read
the office before him and failed WRONG OFFICE on every run.
"""
import unittest
from unittest import mock

from automations.indeed_source_report import offices


class BlankOidSkipped(unittest.TestCase):
    def _run(self, org, cap):
        with mock.patch.object(offices, "ORG", org), \
                mock.patch.object(offices, "CAPTAINSHIP", cap):
            return offices._dedupe()

    def test_blank_none_and_spaces_are_skipped(self):
        out = self._run(
            [("A", "111", "A"), ("B", None, "B")],
            [("C", "", "C"), ("D", "  ", "D"), ("E", "222", "E")])
        self.assertEqual(out, [("111", "A"), ("222", "E")])

    def test_overlap_counted_once(self):
        out = self._run([("A", "111", "A")], [("A", "111", "A")])
        self.assertEqual(out, [("111", "A")])

    def test_live_roster_has_no_blank_office(self):
        self.assertTrue(all(str(o).strip() for o, _n in offices.OFFICES))


if __name__ == "__main__":
    unittest.main()
