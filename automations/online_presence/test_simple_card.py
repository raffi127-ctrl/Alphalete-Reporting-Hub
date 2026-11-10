"""The weekly card's checks that decide a ✅ or ❌.

    python -m unittest automations.online_presence.test_simple_card

Pure functions only: nothing is fetched or posted.
"""
from __future__ import annotations

import unittest

from automations.online_presence import simple_card as sc


class PageNames(unittest.TestCase):
    def test_page_names_need_the_full_name_usernames_can_be_short(self):
        self.assertEqual(sc.names_check("Alphalete Marketing", {
            "facebook": "Alphalete Marketing", "linkedin": "Alphalete Marketing",
            "instagram": "alphaletemarketing", "x": "AlphaleteMrktg",
            "tiktok": "alphalete_marketingtexas"}), (True, ""))

    def test_a_short_page_name_or_an_unrelated_username_is_flagged(self):
        ok, why = sc.names_check("Alphalete Marketing", {
            "facebook": "Alphalete Mktg", "x": "dallasdeals22"})
        self.assertFalse(ok)
        self.assertIn("Facebook: Alphalete Mktg", why)
        self.assertIn("X: dallasdeals22", why)

    def test_llc_on_the_page_is_fine_and_no_names_means_unknown(self):
        self.assertEqual(sc.names_check("Palace Acquisitions",
                                        {"facebook": "Palace Acquisitions LLC",
                                         "instagram": "palaceacq"}), (True, ""))
        self.assertIsNone(sc.names_check("Palace Acquisitions", {}))


class Ideas(unittest.TestCase):
    def _lines(self, **kw):
        lines = {"google": {"new": 0}, "search": {"own": 2, "neg": 3},
                 "posts": {"n": 0, "pages": ["google"]},
                 "info": {"checks": {"Google|business name": True, "Google|website": True,
                                     "Website|name in page title": True}, "names": (True, "")}}
        for k, v in kw.items():
            lines[k].update(v)
        return lines

    def test_an_idea_already_fully_done_is_swapped_for_the_next(self):
        keys = [t["key"] for t in sc.seo_ideas(self._lines(), [])]
        self.assertNotIn("own_site", keys)                  # all three steps ✅
        self.assertEqual(len(keys), 3)

    def test_no_negative_result_no_push_down(self):
        keys = [t["key"] for t in sc.seo_ideas(self._lines(search={"neg": None}), [])]
        self.assertNotIn("push_down", keys)

    def test_never_youtube(self):
        for t in sc.SEO.values():
            self.assertNotIn("youtube", (t["why"] + str(t["how"])).lower())


if __name__ == "__main__":
    unittest.main()
