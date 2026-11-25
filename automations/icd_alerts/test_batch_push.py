"""Resume Helper batch trial (Megan 2026-11-25): 24065 only, dry first."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import batch_push as BP


class BatchTrial(unittest.TestCase):
    def test_only_24065_and_dry(self):
        self.assertEqual(BP.BATCH_OFFICES, {"24065": "dry"})
        self.assertIsNone(BP.mode_for("11280"))
        self.assertLessEqual(BP.BATCH_LIMIT, 10)

    def test_extension_looked_for_in_lucys_profile(self):
        d = Path(tempfile.mkdtemp())
        self.assertFalse(BP.extension_installed(d))
        (d / "Default" / "Extensions" / BP.EXT_ID).mkdir(parents=True)
        self.assertTrue(BP.extension_installed(d))

    def test_no_extension_means_no_browser_work(self):
        page = mock.MagicMock()
        out = BP.run(page, "24065", tempfile.mkdtemp(), live_allowed=True)
        self.assertEqual(out["skipped"], "extension not installed")
        page.locator.assert_not_called()

    def test_other_offices_untouched(self):
        page = mock.MagicMock()
        self.assertEqual(BP.run(page, "11580", "/x", True)["mode"], "off")
        page.locator.assert_not_called()

    def test_switches_off_after_two_blocks(self):
        d = Path(tempfile.mkdtemp()) / "s.json"
        with mock.patch.object(BP, "_state_path", lambda: d):
            BP._note_block("24065", True)
            self.assertFalse(BP.switched_off_today("24065"))
            BP._note_block("24065", True)
            self.assertTrue(BP.switched_off_today("24065"))


if __name__ == "__main__":
    unittest.main()
