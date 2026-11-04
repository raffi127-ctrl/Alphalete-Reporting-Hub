"""Brian Tran, 2026-10-30: his office shut down and 9b06a399 set him to
__SKIP__ in the committed icd_office_mappings.json, but daily-focus kept
pulling office 23082 every morning — the machine's LOCAL output/ mapping still
held "brian tran": "23082", and local wins. A committed __SKIP__ must beat it;
every other local entry still wins as before.

    python -m unittest automations.recruiting_report.test_committed_skip_wins
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.recruiting_report import daily_focus as df


class CommittedSkipWins(unittest.TestCase):
    def _load(self, base, local):
        with tempfile.TemporaryDirectory() as d:
            b, l = Path(d) / "base.json", Path(d) / "local.json"
            b.write_text(json.dumps(base))
            l.write_text(json.dumps(local))
            with mock.patch.object(df, "BASE_OVERRIDES_PATH", b), \
                    mock.patch.object(df, "OVERRIDES_PATH", l):
                return df._load_overrides(), df._is_skipped("BRIAN TRAN")

    def test_committed_skip_beats_a_stale_local_office_id(self):
        got, skipped = self._load({"brian tran": "__SKIP__"},
                                  {"brian tran": "23082"})
        self.assertEqual(got["brian tran"], "__SKIP__")
        self.assertTrue(skipped)

    def test_local_still_wins_over_a_committed_office_id(self):
        got, _ = self._load({"kim rodriguez": "23576"},
                            {"kim rodriguez": "11111"})
        self.assertEqual(got["kim rodriguez"], "11111")


if __name__ == "__main__":
    unittest.main()
