"""Rep rows are recognised by the word Agent at any hierarchy depth (Steve, 2026-10-21)."""
import unittest
from automations.shared import saraplus as S


class AgentDepthTest(unittest.TestCase):
    def _row(self, kind, name, n):
        r = [""] * (max(S.COL_ROWTYPE, S.COL_INTERNET["records"]) + 1)
        r[S.COL_ROWTYPE] = kind; r[S.COL_INTERNET["name"]] = name; r[S.COL_INTERNET["records"]] = str(n)
        return r

    def test_any_depth_of_agent_row_counts(self):
        rows = [self._row("6_Agent", "ANA A", 3), self._row("7_Agent", "BEN B", 2), self._row("4_Agent", "CAL C", 1)]
        self.assertEqual(S.parse_records(rows), {"ANA A": 3, "BEN B": 2, "CAL C": 1})

    def test_group_and_territory_rows_still_skipped(self):
        rows = [self._row("5_Territory", "WEST", 40), self._row("3_Location", "DALLAS", 90), self._row("6_Agent", "ANA A", 3)]
        self.assertEqual(S.parse_records(rows), {"ANA A": 3})


if __name__ == "__main__":
    unittest.main()
