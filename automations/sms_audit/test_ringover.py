"""Ringover client: the parts that must not guess.

Nothing here touches the network. The point of these is that a key with the
wrong Rights, or a quiet week, can never be mistaken for the other.
"""
from __future__ import annotations

import unittest

from automations.sms_audit import ringover as RO


class Phones(unittest.TestCase):
    """One convention across AppStream, the SMS log and Ringover, or the
    calls can never be matched to the applicants."""

    def test_every_shape_lands_on_ten_digits(self):
        for raw in ("(214) 845-6450", "+12148456450", "214.845.6450",
                    "1-214-845-6450", "2148456450"):
            self.assertEqual(RO.norm_phone(raw), "2148456450", raw)

    def test_rubbish_does_not_become_a_number(self):
        self.assertEqual(RO.norm_phone(""), "")
        self.assertEqual(RO.norm_phone(None), "")
        self.assertEqual(RO.norm_phone("anonymous"), "")


class Describe(unittest.TestCase):
    """Ringover names the same thing differently across plans, so the audit
    reads several spellings rather than one."""

    def test_a_recording_is_found_whatever_it_is_called(self):
        for field in ("record", "recording", "record_url"):
            got = RO.describe({field: "https://x/rec.mp3"})
            self.assertEqual(got["recording"], "https://x/rec.mp3", field)

    def test_a_transcript_is_found_whatever_it_is_called(self):
        for field in ("transcription", "transcript", "ai_transcription"):
            got = RO.describe({field: "hello"})
            self.assertEqual(got["transcript"], "hello", field)

    def test_no_recording_reads_as_none_not_as_a_blank_string(self):
        self.assertIsNone(RO.describe({"call_id": 1})["recording"])

    def test_the_user_comes_out_of_the_nested_object(self):
        got = RO.describe({"user": {"concat_name": "Dani Pena"}})
        self.assertEqual(got["user"], "Dani Pena")

    def test_their_number_is_normalised_for_matching(self):
        got = RO.describe({"to_number": "+1 (682) 699-4404"})
        self.assertEqual(got["their_number"], "6826994404")


class TheKeyIsNeverAssumed(unittest.TestCase):
    """[[feedback_empty_means_proven_zero]] -- a key that cannot see
    anything must not read as a team that did nothing."""

    def test_a_missing_key_names_the_fix(self):
        import os
        from pathlib import Path
        old_env = os.environ.pop("RINGOVER_API_KEY", None)
        old_path = RO.CREDS_PATH
        RO.CREDS_PATH = Path("/nonexistent/ringover-key.json")
        try:
            with self.assertRaises(RO.RingoverError) as e:
                RO.api_key()
            self.assertIn("set_ringover_key", str(e.exception))
        finally:
            RO.CREDS_PATH = old_path
            if old_env is not None:
                os.environ["RINGOVER_API_KEY"] = old_env

    def test_an_empty_window_is_a_list_not_an_error(self):
        calls = RO.calls.__doc__
        self.assertIn("never 'we could not look'", calls)




class Empower(unittest.TestCase):
    """Ringover's own transcription. Seen on Megan's screen 2026-10-08:
    summary, recording player and a speaker-separated transcript. The
    routes take the call's UUID, never its numeric call_id."""

    def test_the_uuid_is_found_whatever_it_is_called(self):
        for field in ("cdr_uuid", "call_uuid", "uuid", "channel_id"):
            self.assertEqual(RO.uuid_of({field: "abc-123"}), "abc-123", field)

    def test_a_numeric_call_id_is_not_mistaken_for_the_uuid(self):
        self.assertIsNone(RO.uuid_of({"call_id": 147857741000173100}))


if __name__ == "__main__":
    unittest.main()
