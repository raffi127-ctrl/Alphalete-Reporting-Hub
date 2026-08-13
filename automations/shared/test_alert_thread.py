"""Pins the "short in the channel, long in the thread" contract (2026-08-13).

The bug this guards: the Vantura board audit's 13 findings went into the CHANNEL
message and filled the whole screen. What must stay true:

  (a) a long alert leaves a SHORT parent and pushes the bulk into replies
  (b) NOTHING is truncated — every item still arrives, chunked across replies
  (c) a ``` block (paste-to-Claude / log tail) never stays in the channel, and a
      block split across two replies is closed + re-opened so both still render

Run:  python -m automations.shared.test_alert_thread   (3.9-safe)
"""
from __future__ import annotations

import unittest

from automations.shared import alert_thread as at
from automations.shared import section_drop_alert as sda

FINDINGS = ["STOPPED SELLING: Rep %d has 0 sales for 9 straight days on the "
            "Sales Board but the Roll Call status still reads A (Active) — "
            "either the rep stopped producing or sales land under another "
            "spelling." % i for i in range(1, 14)]


class SplitTests(unittest.TestCase):
    def test_short_body_stays_whole(self):
        parent, detail = at.split_for_thread(["title", "one short line"])
        self.assertEqual(parent, ["title", "one short line"])
        self.assertEqual(detail, [])

    def test_long_body_moves_to_detail(self):
        lines = ["title"] + FINDINGS
        parent, detail = at.split_for_thread(lines)
        self.assertLess(len("\n".join(parent)), 600)
        self.assertEqual(parent[-1], at.MORE)
        # Nothing lost, and the bulk is in the thread (a first short line may
        # still fit in the parent — that's the point of the limit).
        both = parent + detail
        self.assertTrue(all(f in both for f in FINDINGS))
        self.assertGreaterEqual(len(detail), len(FINDINGS) - 2)

    def test_fence_always_threads(self):
        parent, detail = at.split_for_thread(
            ["title", "short", "```", "PASTE THIS TO CLAUDE", "```"])
        self.assertNotIn("```", "\n".join(parent))
        self.assertIn("PASTE THIS TO CLAUDE", "\n".join(detail))

    def test_headline_survives_even_if_long(self):
        parent, _ = at.split_for_thread(["x" * 900, "more"])
        self.assertTrue(parent[0].startswith("x"))


class ChunkTests(unittest.TestCase):
    def test_nothing_is_dropped(self):
        msgs = at.chunk(["   • " + f for f in FINDINGS * 4])
        self.assertGreater(len(msgs), 1)
        joined = "\n".join(msgs)
        for f in FINDINGS:
            self.assertIn(f, joined)

    def test_every_message_under_limit(self):
        msgs = at.chunk(["   • " + f for f in FINDINGS * 6])
        for m in msgs:
            self.assertLessEqual(len(m), at.CHUNK_LIMIT)

    def test_overlong_single_line_is_split_not_truncated(self):
        line = " ".join("word%d" % i for i in range(2000))
        msgs = at.chunk([line])
        self.assertGreater(len(msgs), 1)
        self.assertIn("word1999", "\n".join(msgs))

    def test_fence_reopened_across_chunks(self):
        lines = ["```"] + ["log line %d" % i for i in range(600)] + ["```"]
        msgs = at.chunk(lines)
        self.assertGreater(len(msgs), 1)
        for m in msgs:
            self.assertEqual(m.count("```") % 2, 0)
        self.assertIn("log line 599", "\n".join(msgs))


class SectionDropTests(unittest.TestCase):
    def test_thirteen_findings_leave_a_short_parent(self):
        parent, detail = sda._compose_parts(
            "vantura-board-audit", FINDINGS, None, "13 finding(s) logged",
            "finding")
        text = "\n".join(parent)
        self.assertLess(len(text), 400)
        self.assertIn("See thread for the list", text)
        self.assertNotIn(FINDINGS[0], text)
        self.assertTrue(all(f in "\n".join(detail) for f in FINDINGS))

    def test_single_drop_stays_inline(self):
        parent, detail = sda._compose_parts(
            "office_metrics", ["ABP"], None, "", "section")
        self.assertEqual(detail, [])
        self.assertIn("*Missing:* ABP", "\n".join(parent))


if __name__ == "__main__":
    unittest.main()
