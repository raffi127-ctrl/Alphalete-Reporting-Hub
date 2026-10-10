"""quantum_fiber posts even while its extract is behind, with a caption note
(Eve 2026-10-09). Other boards keep being withheld."""
import datetime as dt
import unittest

from automations.tableau_screenshots import freshness as fr
from automations.tableau_screenshots import pages as pages_mod
from automations.tableau_screenshots import slack_post as sp


class PostWhenBehindTest(unittest.TestCase):
    def test_quantum_fiber_opts_in(self):
        self.assertEqual(fr.post_when_behind("quantum_fiber"), fr.PARTIAL_DAY_NOTE)

    def test_other_boards_still_withheld(self):
        for p in pages_mod.PAGES:
            if p["id"] != "quantum_fiber":
                self.assertIsNone(fr.post_when_behind(p["id"]), p["id"])

    def test_caption_note_keeps_the_reply_match(self):
        today = dt.date(2026, 10, 9)
        spec = dict(pages_mod.by_id("quantum_fiber"), caption_note=fr.PARTIAL_DAY_NOTE)
        cap = sp.reply_caption(spec, today)
        self.assertTrue(cap.endswith(fr.PARTIAL_DAY_NOTE))
        self.assertTrue(sp._reply_matches({"text": cap}, spec, today))

    def test_no_note_caption_unchanged(self):
        spec = pages_mod.by_id("nds")
        self.assertEqual(sp.reply_caption(spec, dt.date(2026, 10, 9)),
                         f"*{spec['title']} - Oct 9*")


if __name__ == "__main__":
    unittest.main()


class OwedHoldsTest(unittest.TestCase):
    """quantum_fiber's daily hold is the plan, not a miss (Megan 2026-10-10:
    "this error keeps happening daily and multiple times")."""

    HELD = {"quantum_fiber": "DROP Fri", "nds": "behind"}

    def test_morning_drops_post_when_behind_board(self):
        from automations.tableau_screenshots import run as run_mod
        self.assertEqual(run_mod.owed_holds(self.HELD, {}, late_only=False),
                         {"nds": "behind"})

    def test_late_pass_reports_only_what_it_withheld(self):
        from automations.tableau_screenshots import run as run_mod
        # quantum_fiber was sent captioned, so it is no longer in still_behind
        self.assertEqual(run_mod.owed_holds(self.HELD, {"nds": "behind"},
                                            late_only=True),
                         {"nds": "behind"})
        self.assertEqual(run_mod.owed_holds(self.HELD, {}, late_only=True), {})
