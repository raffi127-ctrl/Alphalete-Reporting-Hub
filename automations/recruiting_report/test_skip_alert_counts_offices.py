"""Pins that the Daily Focus skip alert counts OFFICES, not spreadsheet rows.

The bug (2026-09-09): office 23576 is listed on two captainship tabs under two
spellings — "Kim Rodriguez" on Raf's, "KIMBERLY RODRIGUEZ" on Chan's. One office
nobody can reach was reported as

    2 ICD(s) refused by AppStream (KIMBERLY RODRIGUEZ, Kim Rodriguez)

every morning, which reads as two people with two separate access problems. Eve
spent a triage on it before the two names turned out to be one office.

The overlap itself is NOT a mistake to clean up: Raf's Daily Focus tab is a
catch-all of ~32 ICDs spanning ten captainships, so an office appearing on his
tab AND its captain's is the normal shape. The alert has to survive it.

Run:  python -m automations.recruiting_report.test_skip_alert_counts_offices
"""
from __future__ import annotations

import unittest

from automations.recruiting_report import daily_focus as DF


# The real office map is a Sheet-backed lookup; these tests pin the GROUPING,
# so the resolver is stubbed to the two spellings that caused the incident.
_OFFICES = {
    "kim rodriguez": "23576",
    "kimberly rodriguez": "23576",
    "marcial rodriguez": "22512",
    "sam park": "23100",
    "nobody knows": None,
    "also unknown": None,
}


class _StubResolver:
    def __enter__(self):
        self._orig = DF._resolve_office_id
        DF._resolve_office_id = lambda n: _OFFICES.get((n or "").lower().strip())
        return self

    def __exit__(self, *a):
        DF._resolve_office_id = self._orig
        return False


class TwoSpellingsAreOneOffice(unittest.TestCase):
    def setUp(self):
        self.ctx = _StubResolver().__enter__()

    def tearDown(self):
        self.ctx.__exit__()

    def test_the_incident_counts_one_not_two(self):
        n, _txt = DF.describe_offices(["KIMBERLY RODRIGUEZ", "Kim Rodriguez"])
        self.assertEqual(n, 1, "one office, two rows — must report 1")

    def test_both_spellings_still_appear(self):
        """Collapsing the count must not hide a name: whoever reads the alert
        has to be able to find the row on either tab."""
        _n, txt = DF.describe_offices(["KIMBERLY RODRIGUEZ", "Kim Rodriguez"])
        self.assertIn("KIMBERLY RODRIGUEZ", txt)
        self.assertIn("Kim Rodriguez", txt)
        self.assertIn("also listed as", txt)

    def test_distinct_offices_still_count_separately(self):
        n, _ = DF.describe_offices(["Kim Rodriguez", "Marcial Rodriguez"])
        self.assertEqual(n, 2)

    def test_a_single_office_reads_plainly(self):
        """No '(also listed as …)' noise when there is only one spelling."""
        _n, txt = DF.describe_offices(["Sam Park"])
        self.assertEqual(txt, "Sam Park")


class UnmappedNamesNeverCollapse(unittest.TestCase):
    """An unmapped ICD has no office id. Two of them are not evidence of one
    office — merging them on a shared None would invent a duplicate."""

    def setUp(self):
        self.ctx = _StubResolver().__enter__()

    def tearDown(self):
        self.ctx.__exit__()

    def test_two_unmapped_names_stay_two(self):
        n, txt = DF.describe_offices(["Nobody Knows", "Also Unknown"])
        self.assertEqual(n, 2)
        self.assertIn("Nobody Knows", txt)
        self.assertIn("Also Unknown", txt)

    def test_an_unmapped_name_does_not_swallow_a_mapped_one(self):
        n, _ = DF.describe_offices(["Nobody Knows", "Sam Park"])
        self.assertEqual(n, 2)


class GroupingIsStableAndLossless(unittest.TestCase):
    def setUp(self):
        self.ctx = _StubResolver().__enter__()

    def tearDown(self):
        self.ctx.__exit__()

    def test_no_name_is_ever_dropped(self):
        names = ["KIMBERLY RODRIGUEZ", "Kim Rodriguez", "Sam Park",
                 "Nobody Knows"]
        got = {n for _oid, group in DF.group_by_office(names) for n in group}
        self.assertEqual(got, set(names))

    def test_order_does_not_change_the_answer(self):
        a = DF.describe_offices(["Kim Rodriguez", "KIMBERLY RODRIGUEZ"])
        b = DF.describe_offices(["KIMBERLY RODRIGUEZ", "Kim Rodriguez"])
        self.assertEqual(a, b)

    def test_empty_input_is_zero_offices(self):
        self.assertEqual(DF.describe_offices([]), (0, ""))

    def test_a_resolver_blowup_keeps_the_name(self):
        """A lookup blip must degrade to 'ungrouped', never lose an ICD from
        the alert."""
        orig = DF._resolve_office_id
        try:
            def boom(_n):
                raise RuntimeError("sheet unavailable")
            DF._resolve_office_id = boom
            n, txt = DF.describe_offices(["Kim Rodriguez", "Sam Park"])
            self.assertEqual(n, 2)
            self.assertIn("Kim Rodriguez", txt)
            self.assertIn("Sam Park", txt)
        finally:
            DF._resolve_office_id = orig


class TheRetryListStaysPerRow(unittest.TestCase):
    """--retry-inaccessible re-pulls PER TAB by name. Deduping the manifest's
    failed list to one office would leave the other tab's row unretried
    forever — so the collapse is human-facing only."""

    def test_the_manifest_list_is_not_grouped(self):
        import inspect
        src = inspect.getsource(DF.main) if hasattr(DF, "main") else ""
        if "uniq = sorted(set(skipped) | set(unmapped))" not in src:
            self.skipTest("manifest list moved; re-pin this test to it")
        self.assertNotIn("uniq = ", src.split(
            "uniq = sorted(set(skipped) | set(unmapped))")[1][:200],
            "the failed list must stay row-based")


if __name__ == "__main__":
    unittest.main(verbosity=2)
