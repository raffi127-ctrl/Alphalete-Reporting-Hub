import datetime as dt
import unittest
from unittest import mock

from automations.nds_metrics import run as R


class TextSections(unittest.TestCase):
    D = dt.date(2026, 11, 14)

    def test_churn_shot_is_texted_once_per_day(self):
        calls = []
        state = {"ts": "1", "posted": ["customer_churn"]}
        with mock.patch.object(R, "_text_section", lambda sid, title, paths, today, log=print: calls.append((sid, title, paths)) or True):
            R.text_sections({"customer_churn": "/x/churn.png", "churn_rates": "/x/r.png",
                             "pct_on_board": "/x/p.png"}, self.D, state)
            R.text_sections({"customer_churn": "/x/churn.png", "churn_rates": "/x/r.png"}, self.D, state)
        self.assertEqual(calls, [("churn_rates", "NDS Churn Rates", ["/x/r.png"]),
                                 ("customer_churn", "NDS Customer Churn", ["/x/churn.png"])])
        self.assertEqual(state["texted"], ["churn_rates", "customer_churn"])

    def test_force_retexts(self):
        calls = []
        state = {"texted": ["customer_churn"]}
        with mock.patch.object(R, "_text_section", lambda *a, **k: calls.append(a[0]) or True):
            R.text_sections({"customer_churn": "/x/c.png"}, self.D, state, force=True)
        self.assertEqual(calls, ["customer_churn"])

    def test_failed_queue_is_not_marked_texted(self):
        state = {}
        with mock.patch.object(R, "_text_section", lambda *a, **k: False):
            R.text_sections({"customer_churn": "/x/c.png"}, self.D, state)
        self.assertEqual(state["texted"], [])

    def test_route_goes_to_both_chains(self):
        from automations.b2b_dispositions import config as B
        for sid in ("customer_churn", "churn_rates", "churn_by_rep"):
            self.assertIn(sid, R.TEXT_SECTIONS)
            self.assertEqual(B.TEXT_ROUTES[("NDS METRICS", "nds_" + sid)],
                             [B.TEXT_GROUP_ATT, B.TEXT_GROUP_ALL])


if __name__ == "__main__":
    unittest.main()
