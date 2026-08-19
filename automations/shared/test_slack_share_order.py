"""Posting several images into one thread in OUR order (`wait_for_share`).

WHY (Eve 2026-08-19). files_upload_v2 returns when the upload finishes, but
Slack posts the share message when it has finished PROCESSING the file — so
uploads fired back to back land in size order, not call order. The 'Knocks for
other offices' thread came out as both Time Gaps followed by both Total Knocks
instead of the per-office grouping Eve asked for ("Time Gaps + Knocks Sahil,
Time Gaps + Knocks Chan"). It only showed up the first day both offices ran in
ONE pass; before that they ran half an hour apart, which hid it.

The rules that have to hold: it waits for the RIGHT file, it gives up rather
than stalling a report, and a Slack read that fails is never fatal.

    python -m unittest automations.shared.test_slack_share_order
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import slack_metrics_post as smp


class _Client:
    """Thread that reveals its messages one poll at a time, like Slack does."""

    def __init__(self, reveals, *, raises=0):
        self._reveals = list(reveals)   # messages become visible in this order
        self._shown = []
        self._raises = raises
        self.polls = 0

    def conversations_replies(self, **kw):
        self.polls += 1
        if self._raises > 0:
            self._raises -= 1
            raise RuntimeError("slack hiccup")
        if self._reveals:
            self._shown.append(self._reveals.pop(0))
        return {"messages": list(self._shown)}


def _msg(file_id=None, text=""):
    m = {"text": text}
    if file_id:
        m["files"] = [{"id": file_id}]
    return m


class WaitForShare(unittest.TestCase):
    def setUp(self):
        # Don't actually sleep between polls.
        self.sleep = mock.patch.object(smp.time, "sleep", lambda *_: None)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_waits_until_the_file_appears(self):
        c = _Client([_msg("F_OTHER"), _msg("F_MINE")])
        self.assertTrue(smp.wait_for_share(c, "C1", "111.1", "F_MINE"))
        self.assertEqual(c.polls, 2)

    def test_another_file_is_not_mine(self):
        c = _Client([_msg("F_OTHER")])
        self.assertFalse(smp.wait_for_share(c, "C1", "111.1", "F_MINE",
                                            timeout_s=0))

    def test_falls_back_to_the_comment_text(self):
        """No file id in the upload response must not silently disable this."""
        c = _Client([_msg(text="🕐 Time Gaps — Sahil Multani — Aug 18")])
        self.assertTrue(smp.wait_for_share(
            c, "C1", "111.1", "", text="🕐 Time Gaps — Sahil Multani — Aug 18"))

    def test_gives_up_instead_of_stalling(self):
        c = _Client([])                      # the share never shows
        self.assertFalse(smp.wait_for_share(c, "C1", "111.1", "F_MINE",
                                            timeout_s=0))

    def test_a_failing_read_is_not_fatal(self):
        c = _Client([_msg("F_MINE")], raises=1)
        self.assertTrue(smp.wait_for_share(c, "C1", "111.1", "F_MINE"))

    def test_nothing_to_match_on_returns_false(self):
        c = _Client([_msg("F_MINE")])
        self.assertFalse(smp.wait_for_share(c, "C1", "111.1", ""))
        self.assertFalse(smp.wait_for_share(c, "C1", "", "F_MINE"))
        self.assertEqual(c.polls, 0)         # no API call for an impossible wait


class UploadedFileId(unittest.TestCase):
    """Reading the id wrong doesn't raise — it silently turns the wait into a
    no-op — so every response shape the SDK returns is pinned here."""

    def test_v2_files_list(self):
        self.assertEqual(
            smp._uploaded_file_id({"files": [{"id": "F1"}]}), "F1")

    def test_v2_nested_files(self):
        self.assertEqual(
            smp._uploaded_file_id({"files": [{"files": [{"id": "F2"}]}]}), "F2")

    def test_legacy_single_file(self):
        self.assertEqual(smp._uploaded_file_id({"file": {"id": "F3"}}), "F3")

    def test_nothing_usable(self):
        for resp in ({}, {"files": []}, {"file": {}}, {"ok": True}):
            self.assertEqual(smp._uploaded_file_id(resp), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
