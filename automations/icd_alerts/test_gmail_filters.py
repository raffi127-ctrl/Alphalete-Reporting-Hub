"""One Google Allow, and Lucy makes the Gmail filter herself (gmail_filters).
2026-11-12.

What must hold: the filter Lucy makes is EXACTLY the one the hand-built box
fills in; Lucy only calls it made after reading it back from Gmail; Gmail's 204
"nothing here" is none, not an error; an unticked Gmail box or the wrong
account is asked again; no Allow means the hand steps; the permission is always
thrown away. And Sterling's one filter goes through the same road.

    python -m unittest automations.icd_alerts.test_gmail_filters
"""
from __future__ import annotations

import threading
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from automations.icd_alerts import code_forward as CF
from automations.icd_alerts import gmail_filters as G
from automations.icd_alerts import sterling_forward as SF

SARA = G.Want("alphaletereporting@gmail.com", "SaraPlus codes",
              **{"from": "security.info@saraplus.com"})


class FakeAsk:
    class Cancelled(Exception):
        pass

    def __init__(self, pick=None, typed=""):
        self.pick, self.typed, self.shown = pick, typed, []

    def message(self, body, **_):
        self.shown.append(body)

    def choose(self, prompt, options):
        if self.pick is None:
            raise self.Cancelled()
        return self.pick

    def text(self, prompt):
        return self.typed


class FakeGmail(G.Grant):
    """A Gmail account's settings, in memory."""

    def __init__(self, email="owner@gmail.com", forwards=None, filters=None,
                 post_code=200):
        super().__init__("tok", email)
        self.forwards = forwards if forwards is not None else [
            {"forwardingEmail": "alphaletereporting@gmail.com",
             "verificationStatus": "accepted"}]
        self.filter_list = list(filters or [])
        self.posted, self.post_code, self.revoked = [], post_code, False

    def get(self, path):
        if path == "forwardingAddresses":
            return (200, {"forwardingAddresses": self.forwards}) if self.forwards else (204, {})
        if path == "filters":
            return (200, {"filter": self.filter_list}) if self.filter_list else (204, {})
        return 404, {}

    def post(self, path, body):
        self.posted.append(body)
        if self.post_code == 200:
            self.filter_list.append(dict(body, id="f%d" % len(self.posted)))
        return self.post_code, {}

    def revoke(self):
        self.revoked = True
        self.token = ""


class TheFilterIsExact(unittest.TestCase):
    def test_saraplus_is_from_saraplus_only(self):
        self.assertEqual(CF.FILTER.body(), {
            "criteria": {"from": "security.info@saraplus.com"},
            "action": {"forward": "alphaletereporting@gmail.com"}})

    def test_sterling_is_the_one_filter_to_lucys_sterling_inbox(self):
        # 11/09: everything from Sterling, no subject, to lucysterlingreports@.
        self.assertEqual(SF.ONE_FILTER.body(), {
            "criteria": {"from": "noreply@us.fadv.co"},
            "action": {"forward": "lucysterlingreports@gmail.com"}})

    def test_the_old_subject_filter_is_not_the_one_filter(self):
        old = {"criteria": {"from": "noreply@us.fadv.co", "subject": "Authentication Request"},
               "action": {"forward": "lucysterlingreports@gmail.com"}}
        self.assertFalse(SF.ONE_FILTER.matches(old))

    def test_a_filter_to_somewhere_else_is_not_ours(self):
        other = {"criteria": {"from": "security.info@saraplus.com"},
                 "action": {"forward": "someone@else.com"}}
        self.assertFalse(SARA.matches(other))

    def test_case_and_spaces_do_not_matter(self):
        same = {"criteria": {"from": " Security.Info@SaraPlus.com"},
                "action": {"forward": "AlphaleteReporting@gmail.com"}}
        self.assertTrue(SARA.matches(same))


class LucyMakesIt(unittest.TestCase):
    def test_makes_it_and_reads_it_back(self):
        g = FakeGmail()
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.MADE)
        self.assertEqual(g.posted, [SARA.body()])

    def test_an_empty_gmail_204_is_none_not_an_error(self):
        g = FakeGmail(filters=[])
        self.assertEqual(G.filters(g), [])
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.MADE)

    def test_already_there_is_not_made_twice(self):
        g = FakeGmail(filters=[SARA.body()])
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.MADE)
        self.assertEqual(g.posted, [])

    def test_a_forward_gmail_has_not_accepted_makes_nothing(self):
        for fwd in ([], [{"forwardingEmail": "alphaletereporting@gmail.com",
                          "verificationStatus": "pending"}]):
            g = FakeGmail(forwards=fwd)
            self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.NOT_ACCEPTED)
            self.assertEqual(g.posted, [])

    def test_google_saying_no_is_not_made(self):
        g = FakeGmail(post_code=400)
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.FAILED)

    def test_a_create_that_does_not_read_back_is_not_made(self):
        g = FakeGmail()
        g.post = lambda path, body: (200, {})      # "ok", but nothing there
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.FAILED)

    def test_unreadable_settings_are_not_made(self):
        g = FakeGmail()
        g.get = lambda path: (403, {})
        self.assertEqual(G.make(g, [SARA], say=lambda *_: None), G.FAILED)


class TheAllow(unittest.TestCase):
    def test_permission_is_always_thrown_away(self):
        for g in (FakeGmail(), FakeGmail(post_code=500)):
            with mock.patch.object(G, "allow", return_value=g):
                G.set_up(FakeAsk(), "owner@gmail.com", [SARA], say=lambda *_: None)
            self.assertTrue(g.revoked)

    def test_no_allow_is_declined(self):
        with mock.patch.object(G, "allow", return_value=None):
            self.assertEqual(G.set_up(FakeAsk(), "o@gmail.com", [SARA],
                                      say=lambda *_: None), G.DECLINED)

    def test_set_up_never_raises(self):
        with mock.patch.object(G, "allow", side_effect=RuntimeError("x")):
            self.assertEqual(G.set_up(FakeAsk(), "o@gmail.com", [SARA],
                                      say=lambda *_: None), G.FAILED)

    def test_an_unticked_gmail_box_is_asked_again(self):
        g = FakeGmail()
        ask = FakeAsk()
        with mock.patch.object(G, "_ask_once",
                               side_effect=[("unticked", None), ("ok", g)]) as once:
            self.assertIs(G.allow(ask, "owner@gmail.com"), g)
        self.assertEqual(once.call_count, 2)
        self.assertIn(G.UNTICKED, ask.shown)

    def test_the_wrong_account_is_revoked_and_asked_again(self):
        wrong, right = FakeGmail(email="other@gmail.com"), FakeGmail()
        ask = FakeAsk()
        with mock.patch.object(G, "_ask_once", side_effect=[("ok", wrong), ("ok", right)]):
            self.assertIs(G.allow(ask, "Owner@gmail.com"), right)
        self.assertTrue(wrong.revoked)
        self.assertTrue(any("other@gmail.com" in m and "owner@gmail.com" in m
                            for m in ask.shown))

    def test_gives_up_after_three_tries(self):
        with mock.patch.object(G, "_ask_once", return_value=("unticked", None)) as once:
            self.assertIsNone(G.allow(FakeAsk(), "o@gmail.com"))
        self.assertEqual(once.call_count, G.TRIES)

    def test_the_steps_say_how_to_get_past_googles_warning(self):
        # Megan 2026-11-12: it looks like an error and the links are tiny, so
        # the box says so before anyone reaches for "Back to safety".
        for words in ("LOOK LIKE AN ERROR", "hasn't verified", "Back to safety",
                      "BOTTOM LEFT", "small word \"Advanced\"",
                      "Go to Recruiting Report (unsafe)", "Tick the box next to Gmail"):
            self.assertIn(words, G.ALLOW_STEPS)
        self.assertIn("Advanced", G.UNTICKED, "the retry repeats the tiny clicks")

    def test_the_pages_say_it_too(self):
        from pathlib import Path
        docs = Path(__file__).resolve().parents[2] / "docs"
        for page in ("sara-forward.html", "sterling-setup.html"):
            text = (docs / page).read_text(encoding="utf-8")
            for words in ("look like an error", "Back to safety", "bottom left",
                          "Go to Recruiting Report (unsafe)", "tick the box next to Gmail"):
                self.assertIn(words, text, page)


class GooglesPage(unittest.TestCase):
    """_ask_once for real: a local catcher, Google's redirect, the token."""

    def _run(self, scope, redirect_extra=None, email="owner@gmail.com"):
        calls = []

        def browser(url, say=None):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertEqual(q["login_hint"], ["owner@gmail.com"])
            self.assertEqual(q["scope"], [G.SETTINGS_SCOPE + " email"])
            back = {"state": q["state"][0], "code": "4/abc"}
            back.update(redirect_extra or {})
            url = q["redirect_uri"][0] + "/?" + urllib.parse.urlencode(back)
            threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=5).read(),
                             daemon=True).start()

        def call(url, data=None, token="", json_body=None, method=""):
            calls.append(url)
            if url == G.TOKEN_URL:
                return 200, {"access_token": "tok", "scope": scope}
            if url == G.USERINFO_URL:
                return 200, {"email": email}
            return 200, {}

        with mock.patch.object(G, "_client", return_value=("cid", "sec")), \
                mock.patch.object(G, "_open", side_effect=browser), \
                mock.patch.object(G, "_call", side_effect=call), \
                mock.patch.object(G.time, "sleep", lambda s: None):
            word, grant = G._ask_once(FakeAsk(), "owner@gmail.com", wait_s=5)
        return word, grant, calls

    def test_allow_gives_a_token_for_that_account(self):
        word, grant, _ = self._run(G.SETTINGS_SCOPE + " https://www.googleapis.com/auth/userinfo.email")
        self.assertEqual(word, "ok")
        self.assertEqual((grant.token, grant.email), ("tok", "owner@gmail.com"))

    def test_gmail_unticked_is_revoked_on_the_spot(self):
        word, grant, calls = self._run("https://www.googleapis.com/auth/userinfo.email")
        self.assertEqual((word, grant), ("unticked", None))
        self.assertIn(G.REVOKE_URL, calls)

    def test_a_wrong_state_is_no_allow(self):
        word, _, calls = self._run(G.SETTINGS_SCOPE, {"state": "forged"})
        self.assertEqual(word, "declined")
        self.assertNotIn(G.TOKEN_URL, calls)


class SterlingUsesIt(unittest.TestCase):
    def _go(self, made):
        opened, ask = [], FakeAsk(CF.YES)
        with mock.patch.object(SF, "_saraplus_address", return_value="owner@gmail.com"), \
                mock.patch.object(SF.F, "_open", side_effect=lambda u, s=None: opened.append(u)), \
                mock.patch.object(SF.F, "_copy"), \
                mock.patch("automations.icd_alerts.relay.report_forward", return_value=True), \
                mock.patch("automations.icd_alerts.relay.results_forward_confirmed",
                           return_value=True), \
                mock.patch.object(G, "set_up", return_value=made) as set_up:
            got = SF.walk_through(ask, say=lambda *_: None, office_key="x")
        return got, opened, ask, set_up

    def test_a_filter_lucy_made_opens_no_filter_box(self):
        got, opened, ask, set_up = self._go(G.MADE)
        self.assertEqual(got, "done")
        self.assertEqual(opened, [])
        self.assertNotIn(SF.ONE_FILTER_STEPS, ask.shown)
        self.assertEqual(set_up.call_args.args[1], "owner@gmail.com")
        self.assertEqual(set_up.call_args.args[2], [SF.ONE_FILTER])

    def test_no_allow_opens_the_hand_built_box(self):
        got, opened, ask, _ = self._go(G.DECLINED)
        self.assertEqual(got, "done")
        self.assertEqual(opened, [SF.F.for_account(SF.ONE_FILTER_URL, "owner@gmail.com")])
        self.assertIn(SF.ONE_FILTER_STEPS, ask.shown)


class ItShips(unittest.TestCase):
    def test_the_module_is_in_the_office_package(self):
        from automations.icd_alerts import package
        self.assertIn("automations/icd_alerts/gmail_filters.py", package.AGENT_FILES)


if __name__ == "__main__":
    unittest.main()
