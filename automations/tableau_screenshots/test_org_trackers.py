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


def _late_caps():
    """Stand-in captures for the ~7am catch-up run (`--late-only`): the late
    boards ONLY — today that's B2B Box, which domin8's subset excludes."""
    return [(p, f"/x/{p['id']}.png") for p in pg.PAGES if pg.is_late(p)]


def _reply_ids(plan):
    return [r["file"].replace(".png", "") for r in plan["replies"]]


class _ExplodingClient:
    """Any attribute access is a test failure — proves the no-op path never talks
    to Slack (it must return before smp._client() is even called)."""

    def __getattr__(self, name):
        raise AssertionError(f"Slack was contacted (client.{name}) on a no-op org")


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


class NothingOwedNoOpTest(unittest.TestCase):
    """REGRESSION (2026-07-24). The ~7am Box catch-up ran `--late-only`, so it
    captured only b2b_box — which domin8's subset excludes. select_for_org emptied
    domin8's captures, _post_to_channel made no upload, and post_all returned
    `all(...) if results else False` = ok=False with NO error key, printing
    '⚠ [domin8] C0B395PUUCW post FAILED: see above' where nothing was above. It
    failed identically on all 3 orchestrator retries and hard-failed the whole
    report (exit 1) every single morning. Nothing owed must be a clean no-op."""

    TODAY = dt.date(2026, 7, 24)

    def setUp(self):
        # post_all must return BEFORE building a Slack client; if it ever regresses
        # and calls one, the exploding stub turns it into a failure, not a network
        # call. Patched on the module post_all actually uses (slack_post.smp).
        self._real_client = sp.smp._client
        sp.smp._client = lambda *a, **k: _ExplodingClient()
        self.addCleanup(setattr, sp.smp, "_client", self._real_client)

    def _post(self, org):
        """The LIVE post path (dry_run=False) — the one that broke."""
        return sp.post_all(_late_caps(), pg.PAGES, self.TODAY, org=org)

    def test_box_only_run_is_a_noop_for_domin8_not_a_failure(self):
        res = self._post("domin8")
        self.assertTrue(res["ok"], "a channel owed nothing must not report failure")
        self.assertTrue(res["skipped"])
        self.assertTrue(res["no_op"])
        self.assertEqual(res["channels"], [])   # no post attempted anywhere

    def test_box_only_run_still_posts_to_a_default_org(self):
        """The guard must not swallow the orgs that DO want Box — posting it is the
        catch-up's whole job. These take the REAL post path, which the exploding
        client proves: every channel comes back with the stub's AssertionError, so
        Slack was genuinely reached (and no `no_op` short-circuit fired)."""
        for org in ("alphalete", "carlos_gp"):
            with self.subTest(org=org):
                caps, _, _ = sp.select_for_org(_late_caps(), pg.PAGES, org)
                self.assertEqual([c[0]["id"] for c in caps], ["b2b_box"])
                res = self._post(org)
                self.assertFalse(res.get("no_op"), "Box's own channel was skipped")
                self.assertTrue(res["channels"], "no channel was even attempted")
                for c in res["channels"]:
                    self.assertIn("Slack was contacted", c.get("error", ""))

    def test_noop_is_generic_not_domin8_specific(self):
        """ANY org that gains a subset later gets the same clean no-op — the guard
        keys off 'this run captured nothing for this org', not off a name."""
        orig_t, orig_c = dict(sp.ORG_TRACKERS), dict(sp.ORG_CHANNELS)
        sp.ORG_TRACKERS["_future"] = ["b2b_att_country"]      # no Box
        sp.ORG_CHANNELS["_future"] = ["C_FUTURE_TEST"]
        sp.ORG_LABEL["_future"] = "#future-test"
        try:
            res = self._post("_future")
            self.assertTrue(res["ok"])
            self.assertTrue(res["no_op"])
            self.assertEqual(res["channels"], [])
        finally:
            sp.ORG_TRACKERS.clear(); sp.ORG_TRACKERS.update(orig_t)
            sp.ORG_CHANNELS.clear(); sp.ORG_CHANNELS.update(orig_c)
            sp.ORG_LABEL.pop("_future", None)

    def test_run_exits_zero_when_the_only_failure_was_the_noop_org(self):
        """End of the chain: a no-op org lands in posted_ok, so `posted_bad` is
        empty and run.py returns 0 instead of the daily false exit 1."""
        posted_ok, posted_bad = [], []
        for org in ("domin8",):
            res = self._post(org)
            (posted_ok if res.get("ok") else posted_bad).append(org)
        self.assertEqual(posted_bad, [])
        self.assertEqual(1 if posted_bad else 0, 0)


if __name__ == "__main__":
    unittest.main()
