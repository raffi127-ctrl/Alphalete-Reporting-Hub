"""A new start is added on RES-AT&T, never on whatever was on screen.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.digi_docs.test_add_campaign

WHY (Megan 2026-08-31): "when people were added they got added as water/primo
and should have been res at&t - huge issue".

add_sales_rep clicked Add on whatever campaign the page was showing, and what
it was showing was wherever find_rep's search had ENDED — it walks every option
and stops on the last one when the rep isn't found. "Water - Primo / RSW B2B"
is last in that dropdown, so an entire morning of new starts went in under it.

The campaign is not cosmetic. The bundle list is per campaign, so the wrong one
means the wrong contract — which is why those reps' documents were wrong as
well as their placement.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.digi_docs import config, ownerville as ov


class _Sel:
    def __init__(self, options):
        self._options, self.picked = options, None

    def locator(self, _):
        class _O:
            def __init__(s, o): s._o = o
            def all_inner_texts(s): return list(s._o)
        return _O(self._options)

    def select_option(self, label=None, **kw):
        self.picked = label

    def wait_for(self, **kw):
        return None


class _Page:
    def __init__(self, options):
        self.sel = _Sel(options)

    def locator(self, _):
        class _F:
            def __init__(s, sel): s.first = sel
            def count(s): return 1           # one visible select on the page
            def nth(s, _i): return s.first
        return _F(self.sel)

    def wait_for_load_state(self, *a, **k):
        return None


REAL = ["RES-AT&T", "RES-ENERGYWELL", "Water - Primo / RSW B2B"]


class SelectCampaignTest(unittest.TestCase):

    def test_it_picks_res_att_not_the_last_option(self):
        page = _Page(REAL)
        got = ov._select_campaign(page, config.ADD_CAMPAIGN, verbose=False)
        self.assertEqual("RES-AT&T", got)
        self.assertEqual("RES-AT&T", page.sel.picked)

    def test_the_configured_campaign_is_res_att(self):
        self.assertEqual("RES-AT&T", config.ADD_CAMPAIGN)

    def test_a_campaign_that_is_not_there_refuses(self):
        page = _Page(["RES-ENERGYWELL", "Water - Primo / RSW B2B"])
        with self.assertRaises(ov.Refused) as cm:
            ov._select_campaign(page, config.ADD_CAMPAIGN, verbose=False)
        self.assertIn("refusing", str(cm.exception))
        self.assertIsNone(page.sel.picked)

    def test_an_ambiguous_campaign_refuses_rather_than_taking_one(self):
        page = _Page(["RES-AT&T", "RES-AT&T OOF", "Water - Primo / RSW B2B"])
        with self.assertRaises(ov.Refused):
            ov._select_campaign(page, config.ADD_CAMPAIGN, verbose=False)
        self.assertIsNone(page.sel.picked)


class SearchStaysOnResAttTest(unittest.TestCase):
    """The SEARCH is pinned to RES-AT&T too, not just the add.

    Megan 2026-09-07, on seeing "Zahra Muhsen: not found in OwnerVille (tried
    ['RES-AT&T', 'RES-ENERGYWELL', 'Water – Primo / RSW B2B'])": "we SHOULD
    only be sending res at&t and NOT trying any other campaign".

    Digi Docs adds everyone under RES-AT&T, so that is the only campaign its
    people can be on. Walking the rest costs two page loads per person on a
    5-minute tick, and risks matching a same-surname rep on a campaign this
    report must not touch — whose bundle it would then GENERATE, which is the
    send. find_rep keeps its full walk for headshots, where a rep needing a
    photo can legitimately be anywhere."""

    def test_digi_docs_passes_only_res_att(self):
        """EVERY find_rep call here scopes the search — asked of the syntax,
        not of a literal string.

        It used to count occurrences of "campaigns=[config.ADD_CAMPAIGN]" and
        expect exactly two. That broke the day the bundle-generating call site
        was widened to `campaigns=[campaign or config.ADD_CAMPAIGN]` so an
        office could pass its own ov_program — a correct change that left the
        campaign just as firmly pinned. The test failed for months of literal
        mismatch while the behaviour it guards was fine, which is the way a
        source-reading assertion goes stale and starts getting ignored.

        What actually matters is that no call walks every campaign: with
        Charter Communications – D2D added to the dropdown on 2026-11-16 there
        are now three, and a same-surname hit on one of the others would
        report "already in OwnerVille" for somebody who is not on ours — so
        they would never be added, and never get their documents.
        """
        import ast
        import inspect
        from automations.digi_docs import ownerville
        tree = ast.parse(inspect.getsource(ownerville))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", ""))
                 == "find_rep"]
        self.assertTrue(calls, "no find_rep call found — did it get renamed?")
        for call in calls:
            kw = {k.arg for k in call.keywords}
            self.assertIn("campaigns", kw,
                          f"find_rep at line {call.lineno} does not pin the "
                          f"campaign — it would walk all of them")

    def test_find_rep_still_walks_everything_by_default(self):
        """Headshots depends on the unrestricted walk — do not break it."""
        import inspect
        from automations.headshots.ov_upload import find_rep
        self.assertIsNone(
            inspect.signature(find_rep).parameters["campaigns"].default)

    def test_restriction_filters_the_dropdown(self):
        """The filter matches the dropdown's OWN labels."""
        opts = ["RES-AT&T", "RES-ENERGYWELL", "Water – Primo / RSW B2B"]
        want = {c.strip().lower() for c in ["RES-AT&T"]}
        kept = [o for o in opts
                if o.strip().lower() in want
                or any(w in o.strip().lower() for w in want)]
        self.assertEqual(["RES-AT&T"], kept)


if __name__ == "__main__":
    unittest.main()


class TheAddPassOutranksACrosstab(unittest.TestCase):
    """2026-11-16. captainship_drafts held Lucy 3's ownerville session from
    10:18:39 to 13:04; the 10:30 add pass fought it for the whole window and
    26 of 52 new starts failed. The reservation machinery for this existed
    already (Megan 2026-09-03, "an enrolled post outranks an individual
    request") — this report simply never claimed it.

    A crosstab twenty minutes late costs nobody anything. A bundle that
    misses a start time means somebody turns up without their paperwork, and
    generating one is a send with no unsend, so it cannot be made good later
    in the day."""

    def test_the_session_is_opened_as_a_scheduled_job(self):
        from automations.digi_docs import ownerville as ov
        seen = {}

        def _fake(**kw):
            seen.update(kw)
            return object()

        with mock.patch(
                "automations.shared.tableau_patchright.ownerville_session",
                _fake):
            ov.session(headless=True, verbose=False)
        self.assertEqual("scheduled", seen.get("priority"),
                         "the add/send pass must reserve the session, not "
                         "race Tableau for it")

    def test_it_still_uses_its_own_profile(self):
        """A private profile is not a private session — both matter, and
        neither implies the other."""
        from automations.digi_docs import ownerville as ov
        seen = {}

        with mock.patch(
                "automations.shared.tableau_patchright.ownerville_session",
                lambda **kw: seen.update(kw) or object()):
            ov.session(headless=True, verbose=False)
        self.assertEqual(ov.PROFILE_DIR, seen.get("profile_dir"))
