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


class Score(unittest.TestCase):
    def _lines(self, avg=4.8, new=0, green=3, n=0, problems=1, search_color="yellow"):
        return {"google": {"avg": avg, "new": new}, "search": {"green": green, "color": search_color},
                "posts": {"n": n}, "info": {"color": "red" if problems else "green",
                                            "problems": ["x"] * problems}}

    def test_four_parts_of_25(self):
        total, parts = sc.score(self._lines())
        self.assertEqual(parts, {"google": 13, "search": 15, "posts": 0, "info": 17})
        self.assertEqual(total, 45)

    def test_a_perfect_week_is_100(self):
        total, _ = sc.score(self._lines(avg=5.0, new=3, green=5, n=2, problems=0))
        self.assertEqual(total, 100)

    def test_a_part_lucy_couldnt_check_scores_zero(self):
        _, parts = sc.score(self._lines(search_color="grey"))
        self.assertEqual(parts["search"], 0)


class OneThingAtATime(unittest.TestCase):
    def test_most_damaging_problem_first(self):
        rows = [{"site": "Google", "item": "phone"}, {"site": "Website", "item": "site loads"},
                {"site": "Google", "item": "website link is secure (https)"}]
        self.assertEqual([r["item"] for r in sorted(rows, key=sc._prio)],
                         ["site loads", "website link is secure (https)", "phone"])

    def test_do_this_week_carries_only_the_top_info_fix(self):
        lines = {"google": {"color": "green"}, "search": {"color": "green"},
                 "posts": {"color": "green"},
                 "info": {"fixes": [{"text": "first"}, {"text": "second"}]}}
        texts = [t["text"] for t in sc.todo(lines)]
        self.assertIn("first", texts)
        self.assertNotIn("second", texts)


class WebsiteLinks(unittest.TestCase):
    def _row(self, page, url, ok=True):
        return {"label": f"Your website links to your {page} page", "ok": ok, "found": "",
                "value": "", "page": page, "url": url}

    def test_green_only_when_google_shows_the_page_live(self):
        lines = {"search": {"color": "yellow", "live_links": [
            "https://www.instagram.com/kashmktg/", "https://facebook.com/kashmktg"]}}
        out = sc.confirm_links([self._row("instagram", "https://instagram.com/kashmktg"),
                                self._row("linkedin", "https://www.linkedin.com/company/123")], lines)
        self.assertTrue(out[0]["ok"])
        self.assertIn("live", out[0]["label"])
        self.assertFalse(out[1]["ok"])           # Google can't find it: a real ❌, never a blank (Megan 11/11)

    def test_numeric_linkedin_found_on_google_by_name(self):
        from unittest import mock
        from types import SimpleNamespace
        p = SimpleNamespace(business_name="Kash Marketing")
        hit = {"organic_results": [{"link": "https://www.linkedin.com/company/kash-marketing",
                                    "title": "Kash Marketing | LinkedIn"}]}
        lines = {"search": {"color": "yellow", "live_links": []},
                 "info": {"aliases": {"linkedin": ["123"]}}}
        with mock.patch("automations.brand_audit.collectors.serp._search", return_value=hit):
            out = sc.confirm_links([self._row("linkedin", "https://www.linkedin.com/company/123")], lines, p)
        self.assertTrue(out[0]["ok"])

    def test_a_wrong_account_stays_red(self):
        lines = {"search": {"color": "yellow", "live_links": []}}
        out = sc.confirm_links([self._row("facebook", "https://facebook.com/other", ok=False)], lines)
        self.assertFalse(out[0]["ok"])


class BothLinkStyles(unittest.TestCase):
    def test_number_and_name_style_are_one_account(self):
        from automations.online_presence.consistency import same_account
        al = {"linkedin": {"15255695", "alphalete-marketing"}}
        self.assertTrue(same_account("linkedin", "https://www.linkedin.com/company/15255695",
                                     "https://ar.linkedin.com/company/alphalete-marketing/", al))
        self.assertFalse(same_account("linkedin", "https://www.linkedin.com/company/15255695",
                                      "https://www.linkedin.com/company/someone-else", al))

    def test_facebook_profile_php_keeps_its_number(self):
        from automations.online_presence.consistency import social_handle, account_key
        self.assertEqual(social_handle("https://www.facebook.com/profile.php?id=61550000000001&sk=about"),
                         "facebook.com/61550000000001")
        self.assertEqual(account_key("https://m.facebook.com/profile.php?id=42"), "42")

    def test_zoho_and_google_feed_the_aliases(self):
        al = sc.page_aliases(
            {"panel": [{"name": "LinkedIn", "link": "https://www.linkedin.com/company/alphalete-marketing"}]},
            {"pages": {"linkedin": {"id": "15255695", "name": "Alphalete Marketing"},
                       "instagram": {"id": "1784", "name": "alphaletemarketing"}}})
        self.assertEqual(al["linkedin"], {"15255695", "alphalete-marketing"})
        self.assertIn("alphaletemarketing", al["instagram"])


if __name__ == "__main__":
    unittest.main()
