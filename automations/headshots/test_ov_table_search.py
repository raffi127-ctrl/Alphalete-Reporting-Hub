"""OwnerVille table search must never hit the sidebar "Search menu" box.

    python -m unittest automations.headshots.test_ov_table_search

11/18 evening OwnerVille added a type=search box to the sidebar
(.ovui-navsearch-box) that sits FIRST in the page. Every caller that used
`input[type='search']:visible` + `.first` typed names into the menu: Lucy 3's
11/19 onboarding passes found nobody, Raf's owner submit timed out. Static
check only, no browser and no network.
"""
import re
import unittest
from pathlib import Path

from automations.headshots import ov_upload

ROOT = Path(__file__).resolve().parents[1]
OV_SEARCH_CALLERS = [
    "headshots/ov_upload.py",
    "obcl_ov_sweep/ov_table.py",
    "bg_check_sync/ov_name_sync.py",
    "digi_docs/ownerville.py",
]
BARE = re.compile(r"""locator\(\s*["']input\[type=['"]search['"]\]:visible["']\s*\)""")


class TableSearchSelector(unittest.TestCase):
    def test_selector_is_scoped_to_the_datatables_box(self):
        sel = ov_upload.OV_TABLE_SEARCH
        for part in (p.strip() for p in sel.split(",")):
            self.assertTrue(".dataTables_filter" in part or "[aria-controls]" in part,
                            f"unscoped search selector part: {part!r}")

    def test_no_caller_uses_the_bare_search_selector(self):
        for rel in OV_SEARCH_CALLERS:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(BARE.search(text),
                              f"{rel} still uses a bare input[type='search'] "
                              "locator -- it will hit OwnerVille's menu search")

    def test_digi_docs_bundle_search_skips_a_bare_search_input(self):
        text = (ROOT / "digi_docs/ownerville.py").read_text(encoding="utf-8")
        self.assertNotIn("\"input[type='search']:visible, .select2", text)


if __name__ == "__main__":
    unittest.main()
