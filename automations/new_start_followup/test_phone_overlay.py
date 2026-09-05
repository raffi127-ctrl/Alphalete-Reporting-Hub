"""The leader phone overlay: what may key it, and what a push may not eat.

Two failures these pin down, both found 2026-09-05 after the first live
Saturday sweep:

1. The overlay is keyed by SLACK ID and nothing else. A leader with a blank id
   written under "" would be matched by every OTHER id-less leader — one
   person's number texted into another person's thread.

2. Lucy 1 WRITES this file (the Saturday sweep fills numbers from reception's
   Google Contacts), so the laptop's copy is behind by construction. A
   wholesale push used to replace it and silently ate the sweep's numbers.
   It now merges — and a deliberate removal rides as an empty-value tombstone,
   because a DELETED key is the one edit a merge cannot carry.

Run: python -m unittest automations.new_start_followup.test_phone_overlay
"""
import json
import tempfile
import unittest
from pathlib import Path

from automations.new_start_followup import roster as roster_mod


class LoadPhonesTests(unittest.TestCase):
    def _write(self, obj) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "new-start-leader-phones.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_drops_note_header_blank_keys_and_tombstones(self):
        p = self._write({
            "_note": "machine-local, never committed",
            "U0REAL0001": "+12145551212",
            "": "+19995550000",          # blank id — must never be readable
            "   ": "+19995551111",       # whitespace-only id, same hazard
            "U0REMOVED1": "",            # deliberate-removal tombstone
        })
        phones = roster_mod.load_phones(p)
        self.assertEqual(phones, {"U0REAL0001": "+12145551212"})

    def test_blank_id_leader_never_inherits_a_blank_key(self):
        """The cross-assignment bug, stated directly."""
        phones = roster_mod.load_phones(self._write({"": "+19995550000"}))
        # Nothing readable, so there is no number to mis-hand to anybody.
        self.assertEqual(phones, {})
        blank = roster_mod.Leader("", "Someone With No Slack Id")
        self.assertNotIn(blank.slack_id, phones)

    def test_tombstone_reads_as_no_number_not_as_a_missing_key(self):
        """A tombstone must SURVIVE in the file (so the merge carries the
        removal) while reading as absent."""
        p = self._write({"U0GONE0001": "", "U0HERE0001": "+12145551212"})
        self.assertNotIn("U0GONE0001", roster_mod.load_phones(p))
        raw = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("U0GONE0001", raw)   # still on disk to be pushed


class OverlayIsAMergingPushTests(unittest.TestCase):
    def test_new_start_leader_phones_merges(self):
        """Excluding it meant a laptop push ate every number the Saturday
        sweep had filled in on Lucy 1."""
        from automations.day_orchestrator import mini_control as mc
        self.assertIn("new-start-leader-phones", mc._CRED_FILES_MERGE)
        self.assertIn("new-start-leader-phones", mc._CRED_FILES)

    def test_merge_keeps_local_only_keys_and_lets_the_push_win(self):
        """The exact semantics the fix relies on, via the real action."""
        from automations.day_orchestrator import mini_control as mc
        d = Path(tempfile.mkdtemp())
        path = d / "new-start-leader-phones.json"
        # What Lucy 1 holds: one number only IT has (sweep-filled from
        # Contacts) plus one the laptop also knows, with a stale value.
        path.write_text(json.dumps({
            "U0SWEEPFILL": "+14696443674",
            "U0BOTHHAVE1": "+12140000000",
        }), encoding="utf-8")

        incoming = json.dumps({
            "U0BOTHHAVE1": "+12149313226",   # laptop corrects it
            "U0LAPTOPNEW": "+19725550000",   # laptop adds someone
            "U0REMOVEDME": "",               # deliberate removal, as a tombstone
        })
        orig = mc._CRED_FILES["new-start-leader-phones"]
        mc._CRED_FILES["new-start-leader-phones"] = lambda: path
        try:
            ok, msg = mc._action_set_cred_file(
                "new-start-leader-phones " + incoming)
        finally:
            mc._CRED_FILES["new-start-leader-phones"] = orig
        self.assertTrue(ok, msg)

        merged = json.loads(path.read_text(encoding="utf-8"))
        # The whole point: the sweep's number is still there.
        self.assertEqual(merged["U0SWEEPFILL"], "+14696443674")
        self.assertEqual(merged["U0BOTHHAVE1"], "+12149313226")  # push wins
        self.assertEqual(merged["U0LAPTOPNEW"], "+19725550000")
        self.assertEqual(merged["U0REMOVEDME"], "")
        # and the result names what it kept, so a clobber is visible
        self.assertIn("U0SWEEPFILL", msg)

        # Read back through the real loader: tombstone gone, rest intact.
        phones = roster_mod.load_phones(path)
        self.assertNotIn("U0REMOVEDME", phones)
        self.assertEqual(phones["U0SWEEPFILL"], "+14696443674")


if __name__ == "__main__":
    unittest.main()
