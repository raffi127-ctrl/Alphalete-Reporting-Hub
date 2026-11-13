"""Office launch: domain + email records, all with Cloudflare faked out."""
import unittest
from unittest import mock

from automations.online_presence import launch as L, site_deploy as D


class FakeCF:
    def __init__(self, zones=("kashsales.com",)):
        self.zones, self.records, self.posts = set(zones), [], []

    def __call__(self, method, url, token, **kw):
        if "zones?name=" in url:
            name = url.split("zones?name=")[1]
            return {"result": [{"id": "Z1"}] if name in self.zones else []}
        if url.endswith("/dns_records") and method == "POST":
            self.records.append(kw["json"])
            self.posts.append(kw["json"])
            return {"result": {}}
        if "/dns_records?" in url:
            q = dict(x.split("=", 1) for x in url.split("?", 1)[1].split("&"))
            return {"result": [r for r in self.records if r["type"] == q["type"] and r["name"] == q["name"]]}
        return {"result": {}}


class Launch(unittest.TestCase):
    def setUp(self):
        self.cf = FakeCF()
        self.p1 = mock.patch.object(D, "_call", self.cf)
        self.p2 = mock.patch.object(D, "_keys", return_value={"cloudflare_api_token": "t", "cloudflare_account_id": "a"})
        self.p1.start(); self.p2.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_google_mail_records_added_once(self):
        L.google_mail("kashsales.com", "abc123")
        L.google_mail("kashsales.com", "google-site-verification=abc123")   # re-run is a no-op
        kinds = sorted((r["type"], r["content"]) for r in self.cf.posts)
        self.assertEqual(kinds, [("MX", "smtp.google.com"),
                                 ("TXT", "google-site-verification=abc123"),
                                 ("TXT", "v=spf1 include:_spf.google.com ~all")])

    def test_a_domain_not_bought_stops_before_anything_happens(self):
        with self.assertRaises(SystemExit) as e:
            L.google_mail("notbought.com", "x")
        self.assertIn("buy it there first", str(e.exception))
        self.assertEqual(self.cf.posts, [])

    def test_domain_and_www_point_at_the_site(self):
        with mock.patch.object(D, "attach_domain", return_value={"status": "pending"}):
            L.put_live(None, "kashsales.com", "kash-site")
        self.assertEqual(sorted(r["name"] for r in self.cf.posts), ["kashsales.com", "www.kashsales.com"])
        self.assertTrue(all(r["content"] == "kash-site.pages.dev" and r["type"] == "CNAME" for r in self.cf.posts))


if __name__ == "__main__":
    unittest.main()


class Logos(unittest.TestCase):
    def test_initials_skip_filler_words(self):
        from automations.online_presence import logo_maker as LM
        self.assertEqual(LM.initials("Summit Sales Group"), "S")
        self.assertEqual(LM.initials("Palace Acquisitions LLC"), "PA")

    def test_the_pick_sets_the_site_look(self):
        from automations.online_presence import logo_maker as LM
        x = LM.site_extras_for(dict(LM.STYLES[3], icon="i.png", logo="l.png"))
        self.assertEqual(x["theme"], "warm")
        self.assertEqual(x["colors"]["accent"], LM.STYLES[3]["accent"])
        self.assertEqual(x["logo"], "i.png")
