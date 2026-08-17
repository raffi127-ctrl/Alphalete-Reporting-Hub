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
        # The parent must SAY the rest is in the thread — but not in one fixed
        # phrase: a kind whose run dropped nothing can't honestly say "the list
        # of missing items" and overrides the wording (`see_thread`). Pinning
        # the default string here is what made this test fail on a truthful
        # rewording rather than on a real regression.
        self.assertIn("thread", text.lower())
        self.assertNotIn(FINDINGS[0], text)
        self.assertTrue(all(f in "\n".join(detail) for f in FINDINGS))

    def test_a_paragraph_long_fix_goes_to_the_thread(self):
        """A 240-char remediation in the CHANNEL is the wall of text this split
        exists to prevent — it belongs with the detail it explains."""
        parent, detail = sda._compose_parts(
            "vantura-board-audit", FINDINGS, None, "", "finding")
        self.assertNotIn("*Fix:*", "\n".join(parent))
        self.assertIn("*Fix:*", "\n".join(detail))

    def test_a_short_fix_still_reads_in_the_channel(self):
        """The other half of the rule: a one-line fix is the parent's whole
        value, so threading it would be an extra click for nothing."""
        parent, _ = sda._compose_parts(
            "office_metrics", FINDINGS, {"fix": "re-run it."}, "", "finding")
        self.assertIn("*Fix:* re-run it.", "\n".join(parent))

    def test_single_drop_stays_inline(self):
        parent, detail = sda._compose_parts(
            "office_metrics", ["ABP"], None, "", "section")
        self.assertEqual(detail, [])
        self.assertIn("*Missing:* ABP", "\n".join(parent))


class PhaseCollapseIsNotAThread(unittest.TestCase):
    """2026-08-17: daily_rep_breakdown's Phase-2 drop went out under the
    'section' fallback — "it did NOT post … The thread is live but incomplete …
    re-run only the missing section". That report posts no thread and has no
    section to re-run on its own; it fills Sheet tabs, and the only fix is the
    whole report (Phase 2 resumes from its checkpoint)."""

    ITEMS = ["Phase 2 — ownerville scrape"]
    NOTE = "ownerville scrape (Phase 2) failed."

    def _parts(self, remediation=None):
        return sda._compose_parts("daily-rep-breakdown", self.ITEMS,
                                  remediation, self.NOTE, "phase")

    def test_it_never_claims_a_thread_or_a_post(self):
        text = "\n".join(sum(self._parts(), [])).lower()
        for phrase in ("did not post", "thread is live", "re-post",
                       "don't re-post the whole thread"):
            self.assertNotIn(phrase, text,
                             "a Sheet fill has no thread to send the reader "
                             "looking for (%r)" % phrase)

    def test_it_names_the_phase_and_says_the_run_stopped(self):
        parent = "\n".join(self._parts()[0])
        self.assertIn("stopped at 1 phase this run", parent)
        self.assertIn("did NOT finish", parent)
        self.assertIn("Phase 2 — ownerville scrape", parent)

    def test_the_default_fix_is_the_whole_report(self):
        text = "\n".join(sum(self._parts(), []))
        self.assertIn("WHOLE", text)
        self.assertIn("checkpoint", text)

    def test_the_manifest_remediation_still_wins(self):
        """daily.py ships its own fix (sign into ownerville, then Run Again) —
        the kind's default is only the fallback."""
        parent, detail = self._parts({"fix": "Make sure Report Chrome is "
                                             "running and signed in."})
        self.assertIn("*Fix:* Make sure Report Chrome is running and signed in.",
                      "\n".join(parent + detail))

    def test_phase_no_longer_falls_back_silently(self):
        self.assertIn("phase", sda._KINDS)
        self.assertNotIn("phase", sda._FILL_SHAPED,
                         "a kind with its own wording must not also be listed "
                         "as a 'section' fallback that's fine as-is")


class UnfilledIcdIsLowKey(unittest.TestCase):
    """Megan 2026-08-15: "the alert on Melik just needs to say his is the only
    one not filled so we know that's not a big deal / fail." One ICD without a
    number on a run that filled everything else must read as an FYI, not an
    incident — the reader should be able to close the tab without opening the
    thread."""

    ITEMS = ["Melik El Jaiez (Tony's team, 0-30)"]
    NOTE = ("Every captain tab filled. 1 ICD had recent history but no value "
            "today — usually just no sales left in that window, not a break.")
    REM = {"fix": "Usually nothing. " + "x" * 60}

    def _parts(self, items=None):
        return sda._compose_parts("captainship-cancel-rate",
                                  items or self.ITEMS, self.REM, self.NOTE,
                                  "unfilled_icd")

    def test_parent_names_the_icd_and_says_everything_else_filled(self):
        parent = "\n".join(self._parts()[0])
        self.assertIn("Melik El Jaiez", parent,
                      "the reader must see WHO without opening the thread")
        self.assertIn("every tab filled", parent.lower())
        self.assertIn("1 ICD didn't fill", parent)

    def test_parent_carries_no_incident_language(self):
        parent = "\n".join(self._parts()[0]).lower()
        for word in ("🚨", "dropped", "did not post", "failed", "missing"):
            self.assertNotIn(word.lower(), parent,
                             "a run that did its whole job must not read as a "
                             "break (%r)" % word)
        self.assertIn("not a break", parent)
        self.assertIn("nothing to re-run", parent)

    def test_detail_and_fix_go_to_the_thread(self):
        parent, detail = self._parts()
        text, thread = "\n".join(parent), "\n".join(detail)
        self.assertIn("thread", text.lower())
        self.assertNotIn("*Fix:*", text,
                         "the what-to-check belongs in the thread, not the "
                         "channel line")
        self.assertIn("*Fix:*", thread)
        self.assertIn("Melik El Jaiez", thread)
        self.assertIn(self.NOTE, thread)

    def test_parent_is_short(self):
        self.assertLess(len("\n".join(self._parts()[0])), 400)

    def test_plural_reads_correctly(self):
        parent, detail = self._parts(
            self.ITEMS + ["Andrew Burton (Sahil's team, 30-60)"])
        text = "\n".join(parent)
        self.assertIn("2 ICDs didn't fill", text)
        self.assertIn("Andrew Burton (Sahil's team, 30-60)", text)
        self.assertIn("the ICDs above", text)

    def test_other_kinds_are_unchanged_by_the_items_key(self):
        """{items} / thread_always / fix_in_thread are opt-in per kind — the
        existing wordings must render exactly as before."""
        parent, detail = sda._compose_parts(
            "office_metrics", ["ABP"], None, "", "section")
        self.assertEqual(detail, [])
        self.assertIn("dropped 1 section this run", "\n".join(parent))


if __name__ == "__main__":
    unittest.main()
