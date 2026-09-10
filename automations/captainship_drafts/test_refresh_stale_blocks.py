"""Offline tests for `review_gate.refresh_stale_blocks` — the build re-sealing
the review PDFs it just invalidated (2026-09-10).

The bug it exists for: a rebuild landing after the links are posted leaves every
sealed PDF describing .eml that no longer exist, and the send then refuses each
approved block. On 2026-09-10 that was twelve captains with nothing, announced
as "1 failure(s)".

PATCHING THE REAL MODULE, NOT sys.modules — see test_weekly_pdf_slack.py for
what the shortcut cost. Every door to Slack and Drive is stubbed on the module
object: `_client`, `_find_post`, `replies`, `block_posts`, `build_pdf`,
`upload_pdf`, plus the two digest readers.

    python -m unittest automations.captainship_drafts.test_refresh_stale_blocks
"""
from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest import mock

from automations.captainship_drafts import config
from automations.captainship_drafts import review_gate as RG


_KEEP_TOKEN: object = None
DAY = dt.date(2026, 9, 10)


def setUpModule():
    """Belt AND braces, as in test_weekly_pdf_slack: the patches are the real
    guard, the junk token makes a patch that ever stops working harmless."""
    global _KEEP_TOKEN
    _KEEP_TOKEN = os.environ.get("SLACK_USER_TOKEN")
    os.environ["SLACK_USER_TOKEN"] = "xoxp-not-a-real-token-unit-test"


def tearDownModule():
    if _KEEP_TOKEN is None:
        os.environ.pop("SLACK_USER_TOKEN", None)
    else:
        os.environ["SLACK_USER_TOKEN"] = _KEEP_TOKEN


class _Client:
    """Records chat_postMessage instead of sending it."""

    def __init__(self):
        self.posted = []

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ok": True}


class RefreshStaleBlocksTests(unittest.TestCase):
    """Two real blocks, so "only what was rebuilt" is actually exercised."""

    def setUp(self):
        self.fiber2 = config.BLOCK_BY_KEY["fiber-2"]     # wayne, starr
        self.nds = config.BLOCK_BY_KEY["nds"]            # khalil, colten, jairo
        self.client = _Client()
        self.uploaded = []

    def _run(self, keys, *, sealed, on_disk, thread_texts=(), approved=(),
             posted=("fiber-2", "nds")):
        """Drive the function with every outside edge stubbed.

        `sealed` / `on_disk` are per-block digests: equal means the PDF still
        describes the previews, different means the rebuild invalidated it.
        """
        posts = {k: {"ts": f"{k}.1", "reactions": []} for k in posted}

        def _approver(msg):
            key = msg["ts"].split(".")[0]
            return ("U1", "Evelyn") if key in approved else None

        with mock.patch.object(RG, "_client", return_value=self.client), \
             mock.patch.object(RG, "_is_the_sending_machine",
                               return_value=True), \
             mock.patch.object(RG, "_channel", return_value="C0TEST"), \
             mock.patch.object(RG, "_find_post", return_value={"ts": "1.0"}), \
             mock.patch.object(RG, "replies",
                               return_value=[{"text": t}
                                             for t in thread_texts]), \
             mock.patch.object(RG, "_sent_keys_from",
                               side_effect=lambda t: {
                                   k for txt in thread_texts
                                   for k in RG._keys_in_marker(txt)}), \
             mock.patch.object(RG, "block_posts", return_value=posts), \
             mock.patch.object(RG, "_approver_of", side_effect=_approver), \
             mock.patch.object(RG, "reviewed_digest",
                               side_effect=lambda d, b: sealed[b.key]), \
             mock.patch.object(RG, "eml_digest",
                               side_effect=lambda d, b: on_disk[b.key]), \
             mock.patch.object(RG, "build_pdf",
                               side_effect=lambda d, b: f"/tmp/{b.key}.pdf"), \
             mock.patch.object(RG, "upload_pdf",
                               side_effect=lambda p, **kw: self.uploaded.append(p)
                               or f"https://drive/{p}"):
            return RG.refresh_stale_blocks(DAY, keys, logfn=lambda m: None)

    def test_stale_block_is_resealed(self):
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "OLD", "nds": "SAME"},
                        on_disk={"fiber-2": "NEW", "nds": "SAME"})
        self.assertEqual(out, ["fiber-2"])
        self.assertEqual(self.uploaded, ["/tmp/fiber-2.pdf"])

    def test_untouched_block_is_left_alone(self):
        """A rebuild of fiber-2 must not rewrite the nds PDF — that approval
        was given off a file nothing touched."""
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "OLD", "nds": "OLD"},
                        on_disk={"fiber-2": "NEW", "nds": "NEW"})
        self.assertEqual(out, ["fiber-2"])

    def test_matching_digest_is_not_rewritten(self):
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "SAME", "nds": "SAME"},
                        on_disk={"fiber-2": "SAME", "nds": "SAME"})
        self.assertEqual(out, [])
        self.assertEqual(self.uploaded, [])

    def test_already_mailed_block_keeps_its_pdf(self):
        """The sent PDF is the record of what people received; replacing it
        would swap the evidence for something nobody got."""
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "OLD", "nds": "SAME"},
                        on_disk={"fiber-2": "NEW", "nds": "SAME"},
                        thread_texts=[f"{RG.PARTIAL_SENT_MARKER} starr,wayne"])
        self.assertEqual(out, [])
        self.assertEqual(self.uploaded, [])

    def test_unsealed_pdf_is_left_alone(self):
        """No fingerprint = built before the check existed. Nothing to compare,
        so nothing to correct."""
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "", "nds": ""},
                        on_disk={"fiber-2": "NEW", "nds": "NEW"})
        self.assertEqual(out, [])

    def test_no_review_post_yet_is_a_no_op(self):
        """The 4am build runs hours before the 07:15 links go up."""
        with mock.patch.object(RG, "_is_the_sending_machine",
                               return_value=True), \
             mock.patch.object(RG, "_find_post", return_value=None):
            self.assertEqual(RG.refresh_stale_blocks(DAY, ["wayne"]), [])

    def test_a_box_that_does_not_mail_refuses_to_reseal(self):
        """Re-sealing from the wrong machine is the 2026-08-27 failure with the
        sides swapped: the PDF would describe previews the sender does not
        have, and the send would refuse its own files."""
        touched = []
        with mock.patch.object(RG, "_is_the_sending_machine",
                               return_value=False), \
             mock.patch.object(RG, "_find_post",
                               side_effect=AssertionError("must not ask Slack")), \
             mock.patch.object(RG, "upload_pdf",
                               side_effect=lambda *a, **k: touched.append(a)):
            said = []
            self.assertEqual(
                RG.refresh_stale_blocks(DAY, ["wayne"], logfn=said.append), [])
        self.assertEqual(touched, [])
        self.assertIn("not the one that mails", " ".join(said))

    def test_ticked_block_tells_the_thread(self):
        """Eve's rule: a ✅ that now stands for a different PDF has to say so."""
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "OLD", "nds": "SAME"},
                        on_disk={"fiber-2": "NEW", "nds": "SAME"},
                        approved=("fiber-2",))
        self.assertEqual(out, ["fiber-2"])
        self.assertEqual(len(self.client.posted), 1)
        text = self.client.posted[0]["text"]
        self.assertIn("Fiber 2", text)
        self.assertIn("Evelyn", text)
        self.assertEqual(self.client.posted[0]["thread_ts"], "1.0")

    def test_unticked_block_says_nothing(self):
        """Nobody has looked yet, so there is nothing to warn anyone about."""
        out = self._run(["wayne", "starr"],
                        sealed={"fiber-2": "OLD", "nds": "SAME"},
                        on_disk={"fiber-2": "NEW", "nds": "SAME"})
        self.assertEqual(out, ["fiber-2"])
        self.assertEqual(self.client.posted, [])

    def test_digest_read_failure_does_not_raise(self):
        """Bookkeeping attached to a build must never fail the build."""
        with mock.patch.object(RG, "_client", return_value=self.client), \
             mock.patch.object(RG, "_is_the_sending_machine",
                               return_value=True), \
             mock.patch.object(RG, "_find_post", return_value={"ts": "1.0"}), \
             mock.patch.object(RG, "replies", return_value=[]), \
             mock.patch.object(RG, "block_posts",
                               return_value={"fiber-2": {"ts": "fiber-2.1"}}), \
             mock.patch.object(RG, "reviewed_digest",
                               side_effect=RuntimeError("drive down")):
            self.assertEqual(
                RG.refresh_stale_blocks(DAY, ["wayne"], logfn=lambda m: None),
                [])


class BlockSentWordingTests(unittest.TestCase):
    """The Slack line has to say how many were DELIVERED."""

    def setUp(self):
        self.client = _Client()

    def _mark(self, failures, sent):
        block = config.BLOCK_BY_KEY["fiber-3"]        # tony, chan, sahil
        with mock.patch.object(RG, "_client", return_value=self.client), \
             mock.patch.object(RG, "_channel", return_value="C0TEST"):
            RG.mark_block_sent({"ts": "1.0"}, block, failures, sent=sent)
        return self.client.posted[0]["text"]

    def test_total_failure_says_zero_delivered(self):
        """2026-09-10: the guard refused the whole block and the old wording
        called it 'sent 3 of 3 with 1 failure(s)'."""
        text = self._mark(3, ["tony", "chan", "sahil"])
        self.assertIn("0 of 3 delivered", text)
        self.assertIn("3 failed", text)
        self.assertNotIn("sent 3 of 3", text)

    def test_partial_failure_counts_the_ones_that_landed(self):
        text = self._mark(1, ["tony", "chan", "sahil"])
        self.assertIn("2 of 3 delivered", text)

    def test_clean_send_keeps_the_old_line(self):
        text = self._mark(0, ["tony", "chan", "sahil"])
        self.assertIn("✅", text)
        self.assertIn("on their way", text)


if __name__ == "__main__":
    unittest.main()
