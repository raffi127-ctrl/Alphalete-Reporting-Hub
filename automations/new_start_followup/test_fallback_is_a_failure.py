"""A 1:1 fallback fails the sweep (Megan 2026-09-05: "make the 1:1 fallback
exit 2").

Before this, `return 2 if (failed or out["errors"]) else 0` treated a fallback
as a footnote: a successful 1:1 send sets no error, so if the "Alphalete Group
Text" Shortcut were renamed or its folder bookmark broke, EVERY leader would
drop to 1:1, Raf would fall out of all 24 threads, and the report would still
exit 0 and go green. The only thing catching that was a weekly agent check,
now retired.

Run: python -m unittest automations.new_start_followup.test_fallback_is_a_failure
"""
import tempfile
import unittest
from pathlib import Path

from automations.new_start_followup import texts


class _Leader:
    def __init__(self, label):
        self.name = label
        self.slack_id = "U0" + label.upper()[:8]
        self.phone = "+12145551212"


class _Status:
    def __init__(self, label):
        self.label = label
        self.owed = 1
        self.leader = _Leader(label)


def _outcome(label, route, sent=True, skipped=None):
    return texts.Outcome(_Status(label), "body", sent, skipped=skipped,
                         route=route)


class _Monday:
    """Stands in for a date; only isoformat() is used by the marker path."""

    def __init__(self, s="2026-09-07"):
        self._s = s

    def isoformat(self):
        return self._s


class SoloFallbackTests(unittest.TestCase):
    def test_a_group_send_is_not_a_fallback(self):
        outs = [_outcome("Willvim", "NEW group with Raf"),
                _outcome("Rhea", "group with Raf (iMessage;-;+1)")]
        self.assertEqual(texts.solo_fallbacks(outs), [])

    def test_a_1to1_send_is_a_fallback(self):
        outs = [_outcome("Willvim", "1:1")]
        self.assertEqual([o.label for o in texts.solo_fallbacks(outs)],
                         ["Willvim"])

    def test_an_already_texted_skip_is_not_a_fallback(self):
        """Otherwise every retry would re-report last week's routing."""
        outs = [_outcome("Willvim", "1:1", sent=False,
                         skipped="already texted this week")]
        self.assertEqual(texts.solo_fallbacks(outs), [])

    def test_render_and_exit_code_share_one_definition(self):
        outs = [_outcome("Willvim", "1:1")]
        self.assertIn("NOT IN A GROUP WITH RAF",
                      texts.render(outs, send=True, terminated_note=None))
        self.assertTrue(texts.solo_fallbacks(outs))


class StickyForTheWeekTests(unittest.TestCase):
    """The retry problem: a second run finds everyone .sent, so solo_fallbacks
    is empty and the run would exit 0 — auto-resolving the incident while Raf
    is still missing from the threads."""

    def setUp(self):
        self._orig = texts.MARKER_DIR
        texts.MARKER_DIR = Path(tempfile.mkdtemp())
        self.monday = _Monday()

    def tearDown(self):
        texts.MARKER_DIR = self._orig

    def test_nothing_recorded_when_every_text_made_a_group(self):
        texts.note_fallbacks(self.monday,
                             [_outcome("Willvim", "NEW group with Raf")])
        self.assertEqual(texts.had_fallback(self.monday), [])

    def test_a_fallback_stays_red_on_the_retry(self):
        texts.note_fallbacks(self.monday, [_outcome("Willvim", "1:1")])
        # the retry: everyone short-circuits, so this run sees no fallback...
        retry = [_outcome("Willvim", "1:1", sent=False,
                          skipped="already texted this week")]
        self.assertEqual(texts.solo_fallbacks(retry), [])
        # ...but the week is still marked, which is what keeps the exit non-zero
        self.assertEqual(texts.had_fallback(self.monday), ["Willvim"])

    def test_names_accumulate_across_runs_without_duplicating(self):
        texts.note_fallbacks(self.monday, [_outcome("Willvim", "1:1")])
        texts.note_fallbacks(self.monday, [_outcome("Rhea", "1:1"),
                                           _outcome("Willvim", "1:1")])
        self.assertEqual(texts.had_fallback(self.monday), ["Rhea", "Willvim"])

    def test_a_different_week_starts_clean(self):
        texts.note_fallbacks(self.monday, [_outcome("Willvim", "1:1")])
        self.assertEqual(texts.had_fallback(_Monday("2026-09-14")), [])


if __name__ == "__main__":
    unittest.main()
