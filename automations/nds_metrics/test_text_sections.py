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

    def test_teams_board_goes_to_leaders_only(self):
        """Carlos 2026-11-20: the Teams board texts the B2B leaders chain."""
        from automations.b2b_dispositions import config as B
        self.assertIn("teams_board", R.TEXT_SECTIONS)
        self.assertEqual(B.TEXT_ROUTES[("NDS METRICS", "nds_teams_board")],
                         [B.TEXT_GROUP_ATT])


class OnRequest(unittest.TestCase):
    """2026-11-19: the Teams board goes out when Carlos asks, never with the
    morning thread -- but `--only teams_board --post` posts and texts it."""

    def test_not_in_the_morning_thread_but_postable(self):
        self.assertIn("teams_board", R.ON_REQUEST)
        morning = [s[0] for s in R.thread_sections()]
        self.assertNotIn("teams_board", morning)
        postable = [s[0] for s in R.postable_sections()]
        self.assertIn("teams_board", postable)
        self.assertEqual([s for s in postable if s != "teams_board"], morning)
        for sid in R.HELD_FROM_THREAD | R.RETIRED:
            self.assertNotIn(sid, postable)

    def test_a_morning_run_never_builds_or_texts_it(self):
        built = []
        with mock.patch.object(R, "SECTIONS", [(sid, e, t, (lambda sid: lambda *a: built.append(sid) or "/x/%s.png" % sid)(sid))
                                               for sid, e, t, _fn in R.SECTIONS]), \
                mock.patch.object(R, "pull", lambda today: "p"), \
                mock.patch.object(R, "load_crew", lambda path: ({}, [])), \
                mock.patch.object(R, "source_for", lambda sid: None):
            self.assertEqual(R.main(["--today", "2026-11-19"]), 0)
            self.assertNotIn("teams_board", built)
            self.assertNotIn("order_log", built)
            self.assertIn("pct_on_board", built)
            built.clear()
            self.assertEqual(R.main(["--today", "2026-11-19", "--only", "teams_board"]), 0)
            self.assertEqual(built, ["teams_board"])


class TeamsBoxRows(unittest.TestCase):
    def _grid(self, names):
        g = [["", "REP", "Current Week"]] + [["", "x"]] * 3
        g.append(["", "Teams — Current Week", "Apps", "Total Head Count", "Leaders",
                  "Entry Level", "In Training", "Sales Avg by Rep"])
        g += [["", n, "1"] for n in names]
        return g

    def test_ends_on_unaccounted_for(self):
        from automations.sales_boards.teams_box import box_rows
        g = self._grid(["AT&T NDS", "Cinthya", "Diego", "Unaccounted For"]) + [["", "something below"]]
        self.assertEqual(box_rows(g), (5, 9, 8))

    def test_a_blank_rank_row_does_not_cut_the_box(self):
        from automations.sales_boards.teams_box import box_rows
        g = self._grid(["AT&T NDS", "Cinthya", "", "Unaccounted For"])
        self.assertEqual(box_rows(g), (5, 9, 8))

    def test_no_closing_row_ends_at_the_last_filled_row(self):
        from automations.sales_boards.teams_box import box_rows
        g = self._grid(["AT&T NDS", "Cinthya", "Diego"]) + [["", ""], ["", "far below"]]
        self.assertEqual(box_rows(g), (5, 8, 8))

    def test_no_box_raises(self):
        from automations.sales_boards.teams_box import box_rows
        with self.assertRaises(RuntimeError):
            box_rows([["", "REP"], ["", "Teams"]])


if __name__ == "__main__":
    unittest.main()
