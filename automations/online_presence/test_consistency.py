"""Sign-up answers vs what the internet shows (consistency.py) + the form's checks.

    python -m unittest automations.online_presence.test_consistency

No network: Google's API and the website reads are faked.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.online_presence import consistency as C, offices, signup


def _office(**kw):
    base = dict(key="kash", business_name="Kash Marketing", slack_channel="C1",
                address="100 Main Street, Suite 2, Dallas, TX 75201",
                phone="(214) 555-0100", website="https://kash.example",
                google_link="https://maps.google.com/maps?cid=42",
                gbp_location="accounts/1/locations/2", pages=("instagram",),
                indeed_url="https://www.indeed.com/cmp/Kash")
    base.update(kw)
    return offices.Presence(**base)


LOC = {"path": "accounts/1/locations/2", "title": "Kash Marketing",
       "address": "100 Main St Ste 2, Dallas, TX, 75201", "phone": "214-555-0100",
       "website": "https://www.kash.example/", "verified": True}


class SameThingWrittenDifferently(unittest.TestCase):
    def test_addresses(self):
        self.assertTrue(C.same_address("100 Main Street, Suite 2, Dallas, TX 75201",
                                       "100 Main St Ste 2, Dallas, TX, 75201"))
        self.assertFalse(C.same_address("100 Main St, Dallas, TX 75201",
                                        "100 Main St, Irving, TX 75038"))
        self.assertFalse(C.same_address("100 Main St, Dallas, TX 75201",
                                        "5217 Tennyson Pkwy, Plano, TX 75024"))

    def test_phones_and_sites(self):
        self.assertEqual(C.digits("+1 (214) 555-0100"), C.digits("214.555.0100"))
        self.assertEqual(C.host("https://www.kash.example/"), C.host("kash.example"))
        self.assertEqual(C.city_of("100 Main St, Dallas, TX 75201"), "Dallas")


class GoogleMatches(unittest.TestCase):
    def _run(self, loc):
        with mock.patch("automations.brand_audit.gbp_api.location_for_link", return_value=loc):
            return {r["item"]: r for r in C.google_checks(_office())}

    def test_all_match(self):
        rows = self._run(LOC)
        for item in ("business name", "address", "phone", "website", "listing verified"):
            self.assertTrue(rows[item]["ok"], item)

    def test_wrong_phone_and_city_are_named(self):
        rows = self._run(dict(LOC, phone="972-000-0000", address="1 Elm St, Irving, TX 75038"))
        self.assertFalse(rows["phone"]["ok"])
        self.assertFalse(rows["address"]["ok"])
        self.assertIn("Irving", rows["address"]["found"])

    def test_link_not_ours_yet(self):
        with mock.patch("automations.brand_audit.gbp_api.location_for_link", return_value=None), \
                mock.patch("automations.brand_audit.gbp_api.all_locations", return_value=[]):
            rows = C.google_checks(_office())
        self.assertFalse(rows[0]["ok"])
        self.assertIn("Manager", rows[0]["found"])

    def test_http_website_flagged(self):
        rows = self._run(dict(LOC, website="http://kash.example/"))
        self.assertFalse(rows["website link is secure (https)"]["ok"])


class WebsiteMatches(unittest.TestCase):
    HOME = ('<a href="/contact">Contact</a><a href="https://instagram.com/kash">IG</a>'
            '<p>Call (214) 555-0100</p>')
    CONTACT = "<p>100 Main St Suite 2, Dallas TX 75201</p>"

    def test_phone_address_and_chosen_page_link(self):
        pages = {"https://kash.example": self.HOME, "https://kash.example/contact": self.CONTACT}
        with mock.patch.object(C, "_get", side_effect=lambda u: pages.get(u)):
            rows = {r["item"]: r for r in C.website_checks(
                _office(instagram_url="https://www.instagram.com/kash/"))}
        self.assertTrue(rows["phone"]["ok"])
        self.assertTrue(rows["address"]["ok"])
        self.assertTrue(rows["links to their instagram"]["ok"])

    def test_old_phone_on_site(self):
        with mock.patch.object(C, "_get", return_value="<p>Call 972-111-2222</p>"):
            rows = {r["item"]: r for r in C.website_checks(_office())}
        self.assertFalse(rows["phone"]["ok"])
        self.assertFalse(rows["address"]["ok"])

    def test_site_down(self):
        with mock.patch.object(C, "_get", return_value=None):
            self.assertFalse(C.website_checks(_office())[0]["ok"])


class TheirExactSocialAccounts(unittest.TestCase):
    def test_one_account_many_spellings(self):
        h = C.social_handle
        self.assertEqual(h("https://www.instagram.com/KashMkt/reels/?hl=en"),
                         h("instagram.com/kashmkt"))
        self.assertEqual(h("https://twitter.com/kash"), h("https://x.com/kash"))
        self.assertEqual(h("https://www.linkedin.com/company/kash-co/about/"),
                         h("linkedin.com/company/kash-co"))

    def test_website_linking_an_old_account_is_flagged(self):
        p = _office(instagram_url="https://instagram.com/kashmkt")
        html = '<p>(214) 555-0100 100 Main St 75201</p><a href="https://instagram.com/kash_old">IG</a>'
        with mock.patch.object(C, "_get", return_value=html):
            row = {r["item"]: r for r in C.website_checks(p)}["links to their instagram"]
        self.assertFalse(row["ok"])
        self.assertIn("kash_old", row["found"])

    def test_website_with_no_link_says_so(self):
        p = _office(facebook_url="https://facebook.com/kash")
        with mock.patch.object(C, "_get", return_value="<p>hi</p>"):
            row = {r["item"]: r for r in C.website_checks(p)}["links to their facebook"]
        self.assertFalse(row["ok"])
        self.assertIn("no facebook link", row["found"])


class NeverReadsIndeedOrGlassdoor(unittest.TestCase):
    def test_check_by_hand_no_fetch(self):
        with mock.patch.object(C, "_get", side_effect=AssertionError("fetched")):
            rows = C._directory_checks("Indeed", "https://www.indeed.com/cmp/Kash", _office())
        self.assertIsNone(rows[0]["ok"])               # never a guessed pass
        self.assertIn("Dallas", rows[0]["expected"])
        self.assertIn("open jobs", rows[0]["expected"])

    def test_check_by_hand_is_never_counted_as_a_match(self):
        with mock.patch.object(C, "google_checks", return_value=[]), \
                mock.patch.object(C, "website_checks", return_value=[]):
            rows = C.checks(_office())
        self.assertTrue(all(r["ok"] is None for r in rows))


class SignupAnswers(unittest.TestCase):
    GOOD = {"Owner": "Kash Rai", "Business Name": "Kash Marketing",
            "Address": "100 Main St, Dallas, TX 75201", "Phone": "214 555 0100",
            "Website": "kash.example", "Google Listing Link": "https://maps.app.goo.gl/x",
            "Complaints Email": "hr@kash.example", "Approvers": "Kash Rai",
            "Pages": ["Google"], "Slack Room": "create us one"}

    def test_good_form_passes_and_is_tidied(self):
        self.assertEqual(signup.problems(self.GOOD), [])
        t = signup.tidy(self.GOOD)
        self.assertEqual(t["Phone"], "(214) 555-0100")
        self.assertEqual(t["Website"], "https://kash.example")

    def test_the_four_truths_are_required(self):
        bad = dict(self.GOOD, Address="", Phone="", Website="", **{"Google Listing Link": ""})
        probs = " ".join(signup.problems(bad))
        for word in ("address", "phone", "website", "Google listing link"):
            self.assertIn(word, probs)

    def test_a_page_picked_for_posting_needs_its_link(self):
        probs = signup.problems(dict(self.GOOD, Pages=["Instagram", "Google"]))
        self.assertTrue(any("add your Instagram link" in p for p in probs))
        ok = signup.problems(dict(self.GOOD, Pages=["Instagram"],
                                  **{"Instagram Link": "instagram.com/kash"}))
        self.assertEqual(ok, [])

    def test_a_link_in_the_wrong_box(self):
        probs = signup.problems(dict(self.GOOD, **{"Instagram Link": "facebook.com/kash",
                                                   "Instagram Link": "facebook.com/kash"}))
        self.assertTrue(any("Instagram link should be" in p for p in probs))

    def test_slack_room_question(self):
        self.assertTrue(any("Slack channel" in p for p in
                            signup.problems(dict(self.GOOD, **{"Slack Room": ""}))))
        self.assertTrue(any("Channel ID" in p for p in
                            signup.problems(dict(self.GOOD, **{"Slack Room": "existing"}))))
        self.assertEqual(signup.problems(dict(self.GOOD, **{"Slack Room": "existing",
                                                            "Slack Channel": "C0ABC12DE"})), [])

    def test_a_facebook_link_is_not_a_google_listing(self):
        probs = signup.problems(dict(self.GOOD, **{"Google Listing Link": "facebook.com/kash"}))
        self.assertTrue(any("Google link" in p for p in probs))

    def test_office_row_needs_them_too(self):
        probs = " ".join(offices.Presence(key="k", business_name="K", slack_channel="C",
                                          contact_email="x@y.z", social=False).problems())
        for word in ("office address", "company phone", "company website", "Google listing link"):
            self.assertIn(word, probs)


if __name__ == "__main__":
    unittest.main()
