"""Every NDS Metrics section names where its numbers came from (Carlos
2026-11-08: "any activation report (Sara or Tableau), depending on where you
got the information from ... so I can quickly remember")."""
import unittest

from automations.nds_metrics import run as R

FEEDS = ("Tableau", "SaraPlus", "Vantura Master Sales Board", "Ownerville")


class Sources(unittest.TestCase):
    def setUp(self):
        R._RUN_SOURCES.clear()

    def tearDown(self):
        R._RUN_SOURCES.clear()

    def test_every_section_names_a_feed(self):
        for sid, _emoji, _title, _fn in R.SECTIONS:
            src = R.source_for(sid)
            self.assertTrue(R.SOURCES.get(sid), sid)
            self.assertIn(src.split(" ·")[0], FEEDS, sid)

    def test_run_time_pick_beats_the_default(self):
        self.assertEqual(R.source_for("order_log"), R.TABLEAU_OL)
        R.note_source("order_log", R.SARA_SOH, log=lambda *_: None)
        self.assertEqual(R.source_for("order_log"), R.SARA_SOH)

    def test_caption_carries_the_source(self):
        cap = R.caption("churn_rates", "x", "NDS Churn Rates")
        self.assertEqual(cap.splitlines(),
                         ["x *NDS Churn Rates*",
                          f"_Source: {R.TABLEAU_OL}_"])
        pre = R.caption("top_reps", "y", "NDS Top 50 Reps", " — PREVIEW")
        self.assertTrue(pre.startswith("y *NDS Top 50 Reps* — PREVIEW\n"))

    def test_unknown_section_is_honest(self):
        self.assertEqual(R.source_for("nope"), "(not recorded)")


if __name__ == "__main__":
    unittest.main()
