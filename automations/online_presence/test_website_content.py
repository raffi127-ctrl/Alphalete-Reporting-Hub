"""Website content scan: only real, quoted mistakes reach the card."""
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.online_presence import website_content as W

PAGES = [{"url": "https://kash.com", "text": "We are hiring young guys. Call (214) 555-0199. Grate service."}]


class RealOnly(unittest.TestCase):
    def test_made_up_quote_is_dropped(self):
        issues = [{"kind": "spelling", "page": "https://kash.com", "quote": "Grate service", "fix": "Great service", "why": ""},
                  {"kind": "grammar", "page": "https://kash.com", "quote": "not on the page", "fix": "x", "why": ""}]
        self.assertEqual([i["quote"] for i in W.real(issues, PAGES)], ["Grate service"])

    def test_no_change_fix_is_dropped(self):
        same = [{"kind": "spelling", "page": "https://kash.com", "quote": "Grate service", "fix": "grate service", "why": ""}]
        self.assertEqual(W.real(same, PAGES), [])


class Rows(unittest.TestCase):
    def _p(self):
        return SimpleNamespace(website="kash.com", business_name="Kash", phone="", address="",
                               campaign="att", path=lambda n: mock.MagicMock())

    def test_three_rows_one_per_kind(self):
        res = {"pages": ["https://kash.com"], "issues": [
            {"kind": "rules", "page": "https://kash.com", "quote": "hiring young guys", "fix": "hiring", "why": ""},
            {"kind": "spelling", "page": "https://kash.com", "quote": "Grate service", "fix": "Great service", "why": ""}]}
        with mock.patch.object(W, "check", return_value=res):
            rows = {r["item"]: r for r in W.rows(self._p())}
        self.assertFalse(rows["hiring wording follows the rules"]["ok"])
        self.assertFalse(rows["no spelling or grammar mistakes"]["ok"])
        self.assertTrue(rows["info on the site is correct"]["ok"])
        self.assertIn("Grate service", rows["no spelling or grammar mistakes"]["found"])

    def test_ai_down_is_unknown_not_a_pass(self):
        with mock.patch.object(W, "check", return_value={"pages": ["x"], "issues": None}):
            self.assertTrue(all(r["ok"] is None for r in W.rows(self._p())))

    def test_site_unreadable_adds_nothing(self):
        with mock.patch.object(W, "check", return_value=None):
            self.assertEqual(W.rows(self._p()), [])


if __name__ == "__main__":
    unittest.main()
