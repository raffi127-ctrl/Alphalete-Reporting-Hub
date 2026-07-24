"""Per-channel tracker SELECTION (`slack_post.tracker_ids_for` / `select_for_org`
/ post_all filtering) + opt-in-only boards.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_org_trackers

WHAT THESE GUARD (Cesar/Domin8 2026-07-23). #domin8-b2b-sales wants only a SUBSET
of the trackers — B2B AT&T ("National Tracker"), B2B AT&T CRU ("National CRU"),
and the new Order Tiered Bonus ranking — not the other boards. Two things have to
stay true or a channel gets the wrong feed:
  1. An org with an ORG_TRACKERS selection posts EXACTLY that list, in that order.
  2. An `opt_in_only` board (order_tiered_bonus) reaches ONLY orgs that name it —
     it must never appear in the default org-wide feed (the 8 existing channels).
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.tableau_screenshots import slack_post as sp
from automations.tableau_screenshots import pages as pg


def _caps():
    """Stand-in captures for every non-late tracker, as the morning run produces."""
    return [(p, f"/x/{p['id']}.png") for p in pg.PAGES if not pg.is_late(p)]


def _reply_ids(plan):
    return [r["file"].replace(".png", "") for r in plan["replies"]]


class OrgTrackerSelectionTest(unittest.TestCase):
    TODAY = dt.date(2026, 7, 23)

    def _plan(self, org):
        return sp.post_all(_caps(), pg.PAGES, self.TODAY, dry_run=True, org=org)

    def test_domin8_posts_exactly_its_three_in_order(self):
        self.assertEqual(
            _reply_ids(self._plan("domin8")),
            ["b2b_att_country", "b2b_att_country_cru", "order_tiered_bonus"])

    def test_domin8_has_no_late_note(self):
        # Box isn't in its selection, so nothing is "still coming".
        self.assertEqual(self._plan("domin8")["pending_late"], [])

    def test_opt_in_board_never_reaches_a_default_org(self):
        for org in ("alphalete", "elevate", "carlos_gp", "aeon"):
            with self.subTest(org=org):
                self.assertNotIn("order_tiered_bonus", _reply_ids(self._plan(org)))

    def test_default_org_still_gets_the_full_org_wide_set(self):
        ids = _reply_ids(self._plan("alphalete"))
        # every non-late, non-opt-in board (Box is late → posts on the catch-up)
        expected = [p["id"] for p in pg.PAGES
                    if not pg.is_late(p) and not pg.is_opt_in_only(p)]
        self.assertEqual(sorted(ids), sorted(expected))

    def test_carlos_order_override_still_applies(self):
        # ORG_ORDER (B2B-first) untouched by the selection mechanism.
        self.assertEqual(_reply_ids(self._plan("carlos_gp"))[:2],
                         ["b2b_att_country", "b2b_att_country_cru"])

    def test_opt_in_board_is_excluded_from_default_ids(self):
        self.assertNotIn("order_tiered_bonus", pg.default_ids())
        self.assertIn("order_tiered_bonus",
                      [p["id"] for p in pg.PAGES])  # …but it DOES exist / gets captured

    def test_a_players_mirrors_alphalete_gp_exactly(self):
        """Carlos asked for #a-players-b2b to match #alphalete-gp-sales (7/23).
        They share _B2B_FIRST, so this pins that they can't drift — same header,
        same reply order, same late handling — while still posting to their OWN
        channels."""
        gp = self._plan("carlos_gp")
        ap = self._plan("a_players")
        self.assertEqual(gp["header"], ap["header"])
        self.assertEqual([r["file"] for r in gp["replies"]],
                         [r["file"] for r in ap["replies"]])
        self.assertEqual(gp["pending_late"], ap["pending_late"])
        self.assertNotEqual(gp["channels"], ap["channels"])  # different channels

    def test_unknown_id_in_selection_is_dropped_not_crashed(self):
        orig = dict(sp.ORG_TRACKERS)
        sp.ORG_TRACKERS["_test"] = ["b2b_att_country", "does_not_exist"]
        try:
            got = sp.tracker_ids_for("_test", pg.PAGES)
            self.assertEqual(got, ["b2b_att_country"])
        finally:
            sp.ORG_TRACKERS.clear()
            sp.ORG_TRACKERS.update(orig)


if __name__ == "__main__":
    unittest.main()
