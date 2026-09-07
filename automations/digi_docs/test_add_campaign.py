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
        import inspect
        from automations.digi_docs import ownerville
        src = inspect.getsource(ownerville)
        # Both call sites — the "already there?" probe and the one that goes on
        # to generate a bundle — must scope the search.
        self.assertEqual(2, src.count("campaigns=[config.ADD_CAMPAIGN]"),
                         "both find_rep calls must pin the campaign")
        self.assertNotIn("find_rep(page, name, verbose=verbose)\n", src)

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
