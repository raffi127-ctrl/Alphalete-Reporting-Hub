"""A frozen copy of a Lucy extension must be a finding, not a footnote.

WHAT THIS GUARDS (2026-11-20). Raf's step-2 extension was a PACKED copy in his
Chrome profile, reporting version 1.1.5 against a repo that also said 1.1.5.
Every check passed. His content.js was missing the one-click-one-send guard
added on 11/11 for the double send he himself hit -- 16 background checks sent
twice, 3 seconds apart. The fix was in the repo and could not reach him.

Two holes, both fixed and both pinned here:

  1. The version string cannot see it. Same number, different code. Only the
     bytes know, so drift_against_repo compares files -- while ignoring the
     manifest keys Chrome adds on install and the PNGs it re-encodes, or every
     packed copy reads as different and the real signal drowns.
  2. A packed copy was printed as "OK -- installed and on" with the drift as a
     parenthetical aside, did not count toward `problems`, and so a run whose
     only install was a frozen copy exited 0 saying "installed and on".
     Exit 0 is not green.

    PYTHONPATH=. .venv/bin/python -m unittest \
        automations.shared.test_extension_doctor
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from automations.shared import extension_doctor as ED


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _FakeRepo(unittest.TestCase):
    """A repo holding one extension, and a copy of it we can diverge."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.repo = self.tmp / "checkout"
        self.ext = self.repo / "extension" / "office-admin"
        _write(self.ext / "manifest.json",
               json.dumps({"name": "Lucy BG Send", "version": "1.1.5"}))
        _write(self.ext / "content.js", "// the guard\nlet sending = false;\n")
        _write(self.ext / "README.md", "docs only, never shipped\n")
        (self.ext / "icons").mkdir(parents=True, exist_ok=True)
        (self.ext / "icons" / "lucy-16.png").write_bytes(b"\x89PNG-repo")

        self.copy = self.tmp / "packed" / "1.1.5_0"
        self.copy.mkdir(parents=True)
        for rel in ("manifest.json", "content.js"):
            (self.copy / rel).write_text(
                (self.ext / rel).read_text(encoding="utf-8"), encoding="utf-8")
        (self.copy / "icons").mkdir()
        (self.copy / "icons" / "lucy-16.png").write_bytes(b"\x89PNG-chrome-reencoded")

        self._real = ED.main_checkout
        ED.main_checkout = lambda: self.repo

    def tearDown(self):
        ED.main_checkout = self._real

    def drift(self):
        return ED.drift_against_repo(str(self.copy), "office-admin")


class DriftIgnoresWhatChromeChangesByItself(_FakeRepo):

    def test_a_faithful_copy_reads_as_clean(self):
        self.assertEqual(self.drift(), ([], []))

    def test_the_keys_chrome_adds_to_a_manifest_are_not_drift(self):
        m = json.loads((self.copy / "manifest.json").read_text())
        m.update({"key": "MIIBIjAN...", "update_url": "https://clients2.google.com/"})
        (self.copy / "manifest.json").write_text(json.dumps(m))
        self.assertEqual(self.drift(), ([], []),
                         "Chrome's own install keys were counted as drift")

    def test_a_reencoded_png_is_not_drift(self):
        """Already different in setUp -- Chrome re-encodes every icon."""
        self.assertEqual(self.drift(), ([], []))

    def test_the_readme_is_not_drift(self):
        """It never ships, so a copy without it is not behind."""
        self.assertFalse((self.copy / "README.md").exists())
        self.assertEqual(self.drift(), ([], []))

    def test_metadata_folder_is_skipped(self):
        files = [str(f) for f in ED._code_files(self.ext)]
        (self.ext / "_metadata").mkdir()
        (self.ext / "_metadata" / "verified_contents.json").write_text("{}")
        self.assertEqual([str(f) for f in ED._code_files(self.ext)], files)


class DriftCatchesWhatActuallyMatters(_FakeRepo):

    def test_a_changed_script_is_caught_at_the_same_version(self):
        """Raf's exact case: 1.1.5 both sides, the guard missing on his."""
        (self.copy / "content.js").write_text("// no guard here\n")
        differing, missing = self.drift()
        self.assertEqual(differing, ["content.js"])
        self.assertEqual(missing, [])
        same = json.loads((self.copy / "manifest.json").read_text())["version"]
        self.assertEqual(same, "1.1.5", "the version is identical -- that is the point")

    def test_a_missing_script_is_reported_as_missing(self):
        (self.copy / "content.js").unlink()
        differing, missing = self.drift()
        self.assertEqual((differing, missing), ([], ["content.js"]))

    def test_a_changed_manifest_field_is_caught(self):
        (self.copy / "manifest.json").write_text(
            json.dumps({"name": "Lucy BG Send", "version": "1.1.4"}))
        differing, _ = self.drift()
        self.assertEqual(differing, ["manifest.json"])

    def test_an_unreadable_side_is_unknown_not_clean(self):
        self.assertIsNone(
            ED.drift_against_repo(str(self.tmp / "nope"), "office-admin"),
            "a folder it cannot read must be unknown, never a silent pass")
        self.assertIsNone(ED.drift_against_repo("", "office-admin"))


class APackedCopyIsNotGreen(_FakeRepo):
    """The regression that let Raf's machine report all-clear."""

    def _chrome(self, location: int):
        """A Chrome user-data dir whose one profile holds our extension."""
        root = self.tmp / "chrome"
        prof = root / "Profile 26"
        prof.mkdir(parents=True)
        (root / "Local State").write_text(json.dumps({
            "profile": {"last_used": "Profile 26",
                        "info_cache": {"Profile 26": {"name": "Rafael",
                                                      "user_name": "raf@x"}}}}))
        (prof / "Secure Preferences").write_text(json.dumps({
            "extensions": {
                "ui": {"developer_mode": True},
                "settings": {"dapenpchflbhodfhndnlhojjnfmmabnp": {
                    "location": location,
                    "path": ("dapenpchflbhodfhndnlhojjnfmmabnp/1.1.5_0"
                             if location != 4 else str(self.copy)),
                    "manifest": {"name": "Lucy BG Send", "version": "1.1.5"},
                }}}}))
        if location != 4:
            dest = prof / "Extensions" / "dapenpchflbhodfhndnlhojjnfmmabnp" / "1.1.5_0"
            dest.parent.mkdir(parents=True)
            dest.symlink_to(self.copy, target_is_directory=True)
        ED.chrome_dirs = lambda: [root]
        return root

    def setUp(self):
        super().setUp()
        self._dirs = ED.chrome_dirs

    def tearDown(self):
        ED.chrome_dirs = self._dirs
        super().tearDown()

    def test_a_packed_copy_exits_nonzero_even_when_identical(self):
        """It works today. It will not get the next fix, and that is a fault."""
        self._chrome(location=1)
        self.assertEqual(self.drift(), ([], []), "precondition: identical today")
        self.assertEqual(ED.main([]), 1,
                         "a frozen copy reported all-clear again")

    def test_a_packed_copy_running_old_code_exits_nonzero(self):
        self._chrome(location=1)
        (self.copy / "content.js").write_text("// no guard here\n")
        self.assertEqual(ED.main([]), 1)

    def test_an_unpacked_copy_outside_a_checkout_is_still_a_copy(self):
        self._chrome(location=4)
        self.assertEqual(ED.main([]), 1)

    def test_loaded_from_the_repo_folder_is_clean(self):
        """The control: the same extension, loaded the right way, passes."""
        root = self.tmp / "chrome-ok"
        prof = root / "Profile 1"
        prof.mkdir(parents=True)
        (root / "Local State").write_text(json.dumps({
            "profile": {"last_used": "Profile 1",
                        "info_cache": {"Profile 1": {"name": "Megan"}}}}))
        (prof / "Secure Preferences").write_text(json.dumps({
            "extensions": {"ui": {"developer_mode": True}, "settings": {
                "abc": {"location": 4, "path": str(self.ext),
                        "manifest": {"name": "Lucy BG Send",
                                     "version": "1.1.5"}}}}}))
        ED.chrome_dirs = lambda: [root]
        self.assertTrue(ED.from_a_checkout(str(self.ext), "office-admin"),
                        "the repo folder itself must read as a checkout")
        self.assertEqual(ED.drift_against_repo(str(self.ext), "office-admin"),
                         ([], []), "the repo compared against itself")
