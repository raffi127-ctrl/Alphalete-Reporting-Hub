"""Drift guard for the harvest cutover (Megan 2026-08-25).

Two invariants, both learned the hard way while cutting Tableau access after
they flagged the account:

  1. NO DEAD NEEDS. Everything in CHURN_CLUSTER_NEEDS is pulled every morning by
     harvest_prime whether or not anybody reads it. Three B2B needs sat in that
     list for weeks costing 3 accesses a day for NOBODY: owners_metrics_churn had
     started appending a WIRELESS product param to its B2B views (pull._wireless),
     which changes the cache key, so the declared URLs matched nothing the report
     asked for. Nothing failed and nothing looked wrong — the report just quietly
     scraped live past a cache built for a URL it no longer used.

  2. NO SILENT UN-CUTOVER. A report flipped to HARVEST_MODE=on only benefits
     while its views still hash to a declared need. Add a URL param, re-save a
     custom view under a new GUID, or rename the worksheet, and the flip becomes
     a no-op — again with nothing failing. These tests pin the pairing so that
     shows up here instead of on the Tableau invoice.

A MISS is not a breakage: the adapter falls through to a live scrape. It is a
COST regression, which is exactly the thing nothing else notices.

Run:  python -m automations.harvest.test_cutover_coverage   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import unittest

from automations.harvest.needs import CHURN_CLUSTER_NEEDS, DataNeed, cache_key


def _key(view_url, crosstab_sheet):
    """The cache key the ADAPTER will compute at call time — same defaults
    (filters={}, pull_mode='saved_view') as adapter.try_cache_view."""
    return cache_key(DataNeed(workbook="", view_url=view_url,
                              crosstab_sheet=crosstab_sheet))


def _declared():
    return dict((cache_key(n), n) for n in CHURN_CLUSTER_NEEDS)


def _pairs_captainship_churn():
    from automations.captainship_churn import pull as p
    return [("new-internet", p.NEW_INT_VIEW_URL, p.WORKSHEET),
            ("wireless", p.WIRELESS_VIEW_URL, p.WORKSHEET)]


def _pairs_owners_fiber_and_nds():
    """Only the per-captain fiber + NDS views — the ones this report is cut over
    for. Its B2B views and ALLTEAM backfills are deliberately NOT harvested (see
    the note above CHURN_CLUSTER_NEEDS), so they are not asserted here."""
    from automations.owners_metrics_churn import pull as p
    out = []
    for name in ("FIBER_WAYNE_URL", "FIBER_STARR_URL", "FIBER_CHAN_URL",
                 "FIBER_TONY_URL", "FIBER_SAHIL_URL"):
        out.append((name, getattr(p, name), p.WORKSHEET))
    for name in ("NDS_KHALIL_URL", "NDS_COLTEN_URL", "NDS_JAIRO_URL"):
        out.append((name, getattr(p, name), p.NDS_WORKSHEET))
    return out


def _pairs_single_view_reports():
    from automations.new_internet_churn import pull as ni
    from automations.wireless_churn import pull as wl
    return [("new_internet_churn", ni.VIEW_URL, ni.WORKSHEET),
            ("wireless_churn", wl.VIEW_URL, wl.WORKSHEET)]


def _pairs_office_metrics_churn():
    """All 11 offices pull the SAME two org-wide churn views and slice in
    Python (offices.CHURN_USE_ALL_OFFICE). That sharing is the whole reason
    harvesting them pays, so the test fails loudly if the flag flips back to
    per-office views — at which point declaring them stops being worth it."""
    from automations.office_metrics import offices as off
    from automations.new_internet_churn import pull as ni
    from automations.wireless_churn import pull as wl
    if not getattr(off, "CHURN_USE_ALL_OFFICE", False):
        return []
    return [("office_metrics NI", off.ALL_OFFICE_CHURN_NI, ni.WORKSHEET),
            ("office_metrics WL", off.ALL_OFFICE_CHURN_WL, wl.WORKSHEET)]


class TestFlippedReportsHitTheCache(unittest.TestCase):
    """Every view a cut-over report pulls must resolve to a declared need."""

    def _assert_all_hit(self, pairs):
        declared = _declared()
        missing = [name for name, url, sheet in pairs
                   if _key(url, sheet) not in declared]
        self.assertEqual(
            missing, [],
            "these views no longer match a declared need, so the report is "
            "scraping Tableau live past a warm cache: %s" % (missing,))

    def test_captainship_churn(self):
        self._assert_all_hit(_pairs_captainship_churn())

    def test_owners_metrics_churn_fiber_and_nds(self):
        self._assert_all_hit(_pairs_owners_fiber_and_nds())

    def test_new_internet_and_wireless_churn(self):
        self._assert_all_hit(_pairs_single_view_reports())

    def test_office_metrics_org_wide_churn(self):
        """The 22-pulls-of-2-views case: every office must resolve to the two
        declared org-wide needs, or the whole saving silently evaporates."""
        pairs = _pairs_office_metrics_churn()
        self.assertTrue(pairs, "CHURN_USE_ALL_OFFICE is off — offices are back "
                               "on per-office views and the two org-wide needs "
                               "in the registry now have no consumer")
        self._assert_all_hit(pairs)


class TestNoDeadNeeds(unittest.TestCase):
    """Nothing is harvested that no report actually asks for."""

    # Needs whose consumer injects the URL via the environment
    # (rashad_metrics / aya_metrics set CHURN_NI_VIEW_URL / CHURN_WL_VIEW_URL),
    # so there is no module constant here to compare against. Declared by label
    # rather than silently skipped.
    ENV_INJECTED = ("NI churn — Rashad", "WL churn — Rashad",
                    "NI churn — Aya", "WL churn — Aya")

    def test_every_declared_need_has_a_live_consumer(self):
        consumed = set()
        for _n, url, sheet in (_pairs_captainship_churn()
                               + _pairs_owners_fiber_and_nds()
                               + _pairs_single_view_reports()
                               + _pairs_office_metrics_churn()):
            consumed.add(_key(url, sheet))
        orphans = [n.label for n in CHURN_CLUSTER_NEEDS
                   if cache_key(n) not in consumed
                   and n.label not in self.ENV_INJECTED]
        self.assertEqual(
            orphans, [],
            "harvest_prime pulls these every morning but no report reads them "
            "-- either wire the consumer or drop them from CHURN_CLUSTER_NEEDS: "
            "%s" % (orphans,))


class TestHarvestStaysOneLogin(unittest.TestCase):
    """The churn cluster is all distinct saved views on a shared worksheet, which
    was proved safe on ONE session (2026-07-12). If a future need lands in a
    second isolation group, the harvest silently starts costing an extra Tableau
    sign-in -- and if it lands in the FIRST group while carrying a URL filter
    param, it can corrupt its neighbours instead."""

    def test_single_isolation_group(self):
        from automations.harvest.harvester import _isolation_groups
        groups = _isolation_groups(CHURN_CLUSTER_NEEDS)
        self.assertEqual(len(groups), 1,
                         "churn harvest split into %d logins" % (len(groups),))

    def test_no_declared_need_carries_a_filter_param(self):
        offenders = []
        for n in CHURN_CLUSTER_NEEDS:
            tail = n.view_url.split("?", 1)[1] if "?" in n.view_url else ""
            for part in tail.split("&"):
                if part and not part.startswith(":"):
                    offenders.append((n.label, part))
        self.assertEqual(
            offenders, [],
            "a param-filtered need sharing a worksheet with others leaks its "
            "filter into them (fiber PSS, 2026-08-17) -- isolate it or leave it "
            "live: %s" % (offenders,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
