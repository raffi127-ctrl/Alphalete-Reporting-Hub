"""install.json is a LIST once a machine runs more than one campaign.

Carlos was the first multi-campaign office to install (2026-09-15) and his
setup died at step 7 with "'list' object has no attribute 'get'". The shape
changed when multi-campaign landed; three readers did not.

The crash was the lucky half. Each of those three then wrote its own dict
straight back over the file -- so had the read survived, the write would have
deleted every other campaign on that machine silently.
"""
from __future__ import annotations

import json
import pathlib
import unittest

SETUP = (pathlib.Path(__file__).resolve().parent / "dist" / "setup.py").read_text()


class NothingReadsInstallJsonAsADict(unittest.TestCase):

    def test_no_reader_parses_it_directly(self):
        # Every read goes through _load_current(), which normalises the shape.
        self.assertNotIn(
            'rec = json.loads((CONFIG_DIR / "install.json").read_text())',
            SETUP,
            "a reader still assumes install.json is a single dict")

    def test_no_writer_overwrites_the_whole_file(self):
        for bad in ('    (CONFIG_DIR / "install.json").write_text('
                    'json.dumps(rec, indent=2))',
                    '        (CONFIG_DIR / "install.json").write_text('
                    'json.dumps(rec, indent=2))'):
            self.assertNotIn(bad, SETUP,
                             "a writer still clobbers the other campaigns")

    def test_the_helpers_exist(self):
        for fn in ("def _install_records(", "def _load_current(",
                   "def _save_current("):
            self.assertIn(fn, SETUP)

    def test_the_merge_write_is_untouched(self):
        # write_install_json() legitimately writes the whole list.
        self.assertIn("target.write_text(json.dumps(merged, indent=2))", SETUP)


class TheHelpersKeepOtherCampaigns(unittest.TestCase):
    """Behaviour, checked against the real logic rather than the text."""

    def _helpers(self, tmp, current):
        import types
        mod = types.ModuleType("fake")
        src = []
        keep = False
        for line in SETUP.splitlines():
            if line.startswith("def _install_records("):
                keep = True
            elif keep and line.startswith("def ask_for_ov_name("):
                break
            if keep:
                src.append(line)
        ns = {"json": json, "CONFIG_DIR": tmp, "HERE": tmp}
        exec("\n".join(src), ns)
        return ns

    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "install.json").write_text(json.dumps([
            {"office_key": "carlos", "campaign": "b2b_box"},
            {"office_key": "carlos-nds", "campaign": "nds"},
        ]))

    def test_saving_one_campaign_keeps_the_other(self):
        ns = self._helpers(self.tmp, "carlos")
        rec = {"office_key": "carlos", "campaign": "b2b_box",
               "ov_name": "Carlos Hidalgo"}
        ns["_save_current"](rec)
        after = json.loads((self.tmp / "install.json").read_text())
        keys = sorted(r["office_key"] for r in after)
        self.assertEqual(keys, ["carlos", "carlos-nds"],
                         "saving one campaign deleted the other")
        got = next(r for r in after if r["office_key"] == "carlos")
        self.assertEqual(got["ov_name"], "Carlos Hidalgo")

    def test_a_single_dict_file_still_reads(self):
        # A machine installed before the list shape existed.
        (self.tmp / "install.json").write_text(
            json.dumps({"office_key": "kash", "campaign": "att"}))
        ns = self._helpers(self.tmp, "kash")
        self.assertEqual(ns["_install_records"]()[0]["office_key"], "kash")


if __name__ == "__main__":
    unittest.main()
