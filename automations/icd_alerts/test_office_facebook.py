"""Facebook reviews from the office's own computer + the sealed key hand-off.

    python -m unittest automations.icd_alerts.test_office_facebook

Facebook is faked: nothing reaches the network.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import office_facebook as FB, sealed, social_post as SP


class Sealed(unittest.TestCase):
    def test_round_trip(self):
        priv, pub = sealed.keypair()
        self.assertEqual(sealed.unseal(sealed.seal("EAAG-page-token", pub), priv), "EAAG-page-token")

    def test_the_box_never_holds_the_secret_readable(self):
        _, pub = sealed.keypair()
        import base64
        self.assertNotIn(b"EAAG-page-token", base64.b64decode(sealed.seal("EAAG-page-token", pub)))

    def test_another_computer_cannot_open_it(self):
        _, pub = sealed.keypair()
        other, _ = sealed.keypair()
        with self.assertRaises(ValueError):
            sealed.unseal(sealed.seal("x", pub), other)

    def test_a_changed_box_is_refused(self):
        import base64
        priv, pub = sealed.keypair()
        d = json.loads(base64.b64decode(sealed.seal("secret", pub)))
        d["c"] = ("00" if d["c"][:2] != "00" else "11") + d["c"][2:]
        with self.assertRaises(ValueError):
            sealed.unseal(base64.b64encode(json.dumps(d).encode()).decode(), priv)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.p = [mock.patch.object(FB, "KEY_PATH", d / "k.json"), mock.patch.object(FB, "LOCK_PATH", d / "l.json")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()


class Connect(Base):
    def test_hello_then_key_keeps_the_page_key_and_drops_the_lock(self):
        pub = SP.check({"do": "fb_hello"})["public"]
        box = sealed.seal("PAGE-TOKEN", pub)
        with mock.patch.object(FB, "_graph", return_value={"id": "9", "name": "Alphalete"}):
            res = SP.check({"do": "fb_key", "page_id": "9", "box": box})
        self.assertEqual((res["status"], res["do"]), ("connected", "fb_key"))
        self.assertEqual(json.loads(FB.KEY_PATH.read_text())["token"], "PAGE-TOKEN")
        self.assertFalse(FB.LOCK_PATH.exists())

    def test_key_that_cannot_read_the_page_is_not_kept(self):
        pub = FB.hello({})["public"]
        with mock.patch.object(FB, "_graph", side_effect=RuntimeError("no access")):
            self.assertEqual(FB.install_key({"page_id": "9", "box": sealed.seal("T", pub)})["status"], "error")
        self.assertFalse(FB.KEY_PATH.exists())


class ReadReply(Base):
    def setUp(self):
        super().setUp()
        FB.KEY_PATH.write_text(json.dumps({"page_id": "9", "token": "T"}))

    def test_reads_only_unanswered_and_not_in_hand(self):
        ratings = {"data": [{"open_graph_story": {"id": s}, "recommendation_type": "positive"} for s in "abc"]}

        def g(method, path, params):
            if path.endswith("/ratings"):
                return ratings
            return {"data": [{"from": {"id": "9"}}]} if path.startswith("b/") else {"data": []}
        with mock.patch.object(FB, "_graph", side_effect=g):
            out = SP.check({"do": "fb_reviews", "skip": ["c"]})
        self.assertEqual([r["story"] for r in out["reviews"]], ["a"])

    def test_practice_never_posts(self):
        with mock.patch.object(FB, "_graph", side_effect=AssertionError("posted")):
            self.assertEqual(SP.post({"do": "fb_reply", "story": "a", "comment": "hi"}, False)["status"], "dry_run")

    def test_live_reply_posts_a_comment(self):
        calls = []
        with mock.patch.object(FB, "_graph", side_effect=lambda m, p, q: calls.append((m, p)) or {"data": []}):
            self.assertEqual(SP.post({"do": "fb_reply", "story": "a", "comment": "Thanks!"}, True)["status"], "replied")
        self.assertIn(("POST", "a/comments"), calls)

    # ---- 11/16: a review by a person -> typed on facebook.com as the page ----
    def _graph_refusing(self, m, path, q):
        if m == "POST":
            raise RuntimeError("(#200) Permissions error [code 200, OAuthException]")
        if path.endswith("/comments"):
            return {"data": []}
        return {"name": "Alphalete Marketing"}

    def test_a_refused_reply_is_typed_on_facebook_as_the_page(self):
        from automations.icd_alerts import office_fb_browser as FBB
        with mock.patch.object(FB, "_graph", side_effect=self._graph_refusing), \
             mock.patch.object(FBB, "browser_reply",
                               return_value={"status": "replied", "story": "s1", "via": "browser"}) as br:
            res = FB.reply_job({"story": "s1", "comment": "Thanks!"}, live=True)
        self.assertEqual(res["status"], "replied")
        br.assert_called_once()
        self.assertEqual(br.call_args[0][:3], ("s1", "Thanks!", "Alphalete Marketing"))

    def test_other_errors_do_not_open_a_browser(self):
        from automations.icd_alerts import office_fb_browser as FBB
        def g(m, path, q):
            if m == "POST":
                raise RuntimeError("(#1) An unknown error occurred")
            return {"data": []}
        with mock.patch.object(FB, "_graph", side_effect=g), \
             mock.patch.object(FBB, "browser_reply", side_effect=AssertionError("browser")):
            self.assertEqual(FB.reply_job({"story": "s1", "comment": "x"}, live=True)["status"], "error")

    def test_browser_without_a_facebook_signin_says_so(self):
        from automations.icd_alerts import office_fb_browser as FBB
        import tempfile
        with mock.patch.object(FBB, "PROFILE", Path(tempfile.mkdtemp()) / "none"):
            self.assertEqual(FBB.browser_reply("s1", "x", "Page")["status"], "needs_signin")

    def test_no_key_says_signed_out(self):
        FB.KEY_PATH.unlink()
        self.assertEqual(FB.read_job({})["status"], "signed_out")


if __name__ == "__main__":
    unittest.main()
