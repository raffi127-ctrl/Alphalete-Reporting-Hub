"""Offline tests for the Office Access watch — no ownerville, no Sheets.

What has to hold:

  1. an office listed under a spelling the report CANNOT search for is not
     "granted": announcing it would send the build after an office it then
     fails to impersonate
  2. a row whose action still says "request" is PENDING, not granted — that is
     the state Eve's 8/25 requests sit in until someone approves them
  3. the diff only speaks when something MOVED, and it separates access changes
     from roster churn (an owner who left a captainship is not a revocation)
  4. a half-loaded Office Access table is refused, never reported as "everyone
     lost access"

Run:  python -m automations.knocks_access_watch.test_watch
"""
from __future__ import annotations

import unittest

from automations.knocks_access_watch import audit as A
from automations.knocks_access_watch import run as R

# (office #, company, owner-as-ownerville-spells-it, …, action)
ROWS = [
    ["11280", "Alphalete", "Raf Hidalgo", "", ""],
    ["23171", "Tally Management Group", "Coel Reif", "", ""],
    ["22041", "Kaizen Solutions", "Andre Burton Jr", "", ""],
    ["21959", "Clear View Consultants", "Jay Turnage", "", "Request Access"],
]
# load_aliases() shape: {canonical (the board / Focus tab name):
# [other spellings]} — see focus_office_att.aliases.
ALIASES = {"Andre Burton": ["Andre Burton Jr"]}


class Classify(unittest.TestCase):
    def _one(self, display, rows=None, aliases=None):
        rmap = {"tony": ("Tony's Captainship", [display])}
        rep = A.classify(rmap, rows or ROWS,
                         ALIASES if aliases is None else aliases)
        return rep["tony"]["owners"][0]

    def test_a_granted_office_is_ok(self):
        self.assertEqual(self._one("Coel Reif")["status"], A.OK)

    def test_an_alias_spelling_still_counts(self):
        """ownerville calls him "Andre Burton Jr"; the board says "Andre
        Burton". The alias sheet bridges it, so this IS reachable."""
        got = self._one("Andre Burton")
        self.assertEqual(got["status"], A.OK)
        self.assertEqual(got["matched"], "Andre Burton Jr")

    def test_a_spelling_we_cannot_search_is_not_granted(self):
        """Same office on the list, but no alias — the report's own lookup
        would miss it, so the watch must not announce it as access."""
        got = self._one("Andre Burton", aliases={})
        self.assertEqual(got["status"], A.MISSING)
        self.assertIn("Andre Burton Jr", got["near"])

    def test_still_a_request_is_pending(self):
        self.assertEqual(self._one("Jay Turnage")["status"], A.PENDING)

    def test_absent_is_missing(self):
        self.assertEqual(self._one("Wayne Rude")["status"], A.MISSING)


class TheMasterNeedsNoGrant(unittest.TestCase):
    """Raf's office IS the login (11280), so it never appears in its own
    Office Access list. Read literally, the audit called the healthiest
    captainship 12 of 13 and pointed at the one owner who can never be
    missing (2026-08-25)."""

    def test_master_is_reachable_even_when_unlisted(self):
        rep = A.classify({"rafael": ("Raf's", ["Rafael Hidalgo"])}, [], ALIASES)
        self.assertEqual(rep["rafael"]["owners"][0]["status"], A.MASTER)
        self.assertEqual(A.counts(rep)["rafael"], (1, 1))

    def test_master_is_not_listed_as_a_gap(self):
        rep = A.classify({"rafael": ("Raf's", ["Rafael Hidalgo", "Coel Reif"])},
                         ROWS, ALIASES)
        line = R.summary_lines(rep)[0]
        self.assertIn("2/2 reachable", line)
        self.assertNotIn("waiting on", line)


class Counting(unittest.TestCase):
    def test_counts_only_credit_granted(self):
        rmap = {"tony": ("Tony's", ["Coel Reif", "Jay Turnage",
                                    "Wayne Rude"])}
        rep = A.classify(rmap, ROWS, ALIASES)
        self.assertEqual(A.counts(rep)["tony"], (1, 3))


class Diff(unittest.TestCase):
    def test_a_grant_is_news(self):
        d = R.diff({"tony/Jay Turnage": A.PENDING},
                   {"tony/Jay Turnage": A.OK})
        self.assertEqual([k for k, _w, _s in d["gained"]], ["tony/Jay Turnage"])
        self.assertFalse(d["lost"])

    def test_a_revocation_is_news(self):
        d = R.diff({"tony/Coel Reif": A.OK}, {"tony/Coel Reif": A.MISSING})
        self.assertEqual([k for k, _w, _s in d["lost"]], ["tony/Coel Reif"])

    def test_no_movement_says_nothing(self):
        same = {"tony/Coel Reif": A.OK, "tony/Jay Turnage": A.MISSING}
        d = R.diff(same, dict(same))
        self.assertIsNone(R.change_text(d, {}))

    def test_roster_churn_is_not_an_access_change(self):
        d = R.diff({"tony/Coel Reif": A.OK},
                   {"tony/Coel Reif": A.OK, "starr/Blue Mendoza": A.MISSING})
        self.assertFalse(d["gained"])
        self.assertFalse(d["lost"])
        self.assertEqual(d["added"], [("starr/Blue Mendoza", A.MISSING)])

    def test_message_names_the_coverage(self):
        rep = A.classify({"tony": ("Tony's", ["Coel Reif", "Wayne Rude"])},
                         ROWS, ALIASES)
        text = R.change_text(
            R.diff({"tony/Coel Reif": A.MISSING}, {"tony/Coel Reif": A.OK}),
            rep)
        self.assertIn("tony/Coel Reif", text)
        self.assertIn("1 of 2", text)

    def test_full_coverage_is_called_out(self):
        rep = A.classify({"tony": ("Tony's", ["Coel Reif"])}, ROWS, ALIASES)
        text = R.change_text(
            R.diff({"tony/Coel Reif": A.MISSING}, {"tony/Coel Reif": A.OK}),
            rep)
        self.assertIn("Every captainship ICD is reachable", text)


class ShortRead(unittest.TestCase):
    class _Page:
        """Enough of a patchright Page to walk read_office_access to its guard
        with a table that only ever yields the DataTable's first page."""
        url = ""

        def goto(self, url, *_a, **_k):
            # ownerville redirects the bare root to index.cfm with a freshly
            # minted rqst; everything after that keeps the url it was given.
            self.url = (url + "index.cfm?rqst=ABC123"
                        if url.endswith(".com/") else url)
            return None

        def wait_for_function(self, *_a, **_k):
            return None

        def wait_for_timeout(self, *_a, **_k):
            return None

        def locator(self, sel):
            page = self

            class _Loc:
                def wait_for(self, **_k):
                    return None

                @property
                def first(self):
                    raise RuntimeError("no length selector")

                def all(self):
                    if "tbody tr" in sel:
                        return [page._row() for _ in range(25)]
                    return []

            return _Loc()

        def _row(self):
            class _Cell:
                def inner_text(self_inner):
                    return "x"

            class _Tr:
                def locator(self_inner, _sel):
                    class _L:
                        def all(self_l):
                            return [_Cell(), _Cell(), _Cell()]
                    return _L()
            return _Tr()

    def test_twenty_five_rows_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            A.read_office_access(self._Page())
        self.assertIn("default page size", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
