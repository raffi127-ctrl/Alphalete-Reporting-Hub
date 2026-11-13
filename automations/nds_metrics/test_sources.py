"""The activation reports say 'Source: Sara' or 'Source: Tableau' under
their title; nothing else in the NDS Metrics thread carries a Source line
(Carlos 2026-11-09: "I only want it on the activation reports. You can make
it as simple as 'Source: Sara' or 'Source: Tableau'"). Five since 11/13: the
week-ending board has a Tableau twin posted right after it."""
import unittest

from automations.nds_metrics import run as R

ACTIVATION = {"activation_overview", "activation_revenue",
              "activation_by_rep", "activation_by_week",
              "activation_by_week_tableau"}


class Sources(unittest.TestCase):
    def test_only_the_activation_reports_and_one_word(self):
        self.assertEqual(set(R.SOURCES), ACTIVATION)
        for sid, _emoji, _title, _fn in R.SECTIONS:
            if sid in ACTIVATION:
                self.assertIn(R.source_for(sid), ("Sara", "Tableau"), sid)
            else:
                self.assertIsNone(R.source_for(sid), sid)

    def test_caption_shapes(self):
        self.assertEqual(
            R.caption("activation_by_rep", "x", "NDS Activation Rate by Rep"),
            "x *NDS Activation Rate by Rep*\nSource: Tableau")
        self.assertEqual(
            R.caption("activation_revenue", "y", "T", " — PREVIEW"),
            "y *T* — PREVIEW\nSource: Sara")
        self.assertEqual(R.caption("churn_rates", "z", "NDS Churn Rates"),
                         "z *NDS Churn Rates*")
        self.assertEqual(
            R.caption("activation_by_week_tableau", "w", "NDS Activation Rate by Week Ending (Tableau)"),
            "w *NDS Activation Rate by Week Ending (Tableau)*\nSource: Tableau")


if __name__ == "__main__":
    unittest.main()
