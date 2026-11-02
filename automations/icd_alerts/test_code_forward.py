"""Setup asks for the SaraPlus code forward on the spot (code_forward), and
Lucy 1 files the address (code_answer.record_forwards). 2026-10-29.

What must hold: the address the owner picks is the one sent, and sent WITHOUT
the scrub that would blank it; skipping sends nothing and asks again later;
Lucy 1 keeps one row per office. 2026-11-02: only SaraPlus's mail is forwarded,
the steps warn off Gmail's whole-inbox switch, Lucy 1 accepts Gmail's mail only
for an address on the tab, and we hear if an address forwards anything else.
"""
from __future__ import annotations

import datetime as dt
import http.server
import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import code_answer as CA
from automations.icd_alerts import code_forward as CF
from automations.icd_alerts import post as P
from automations.icd_alerts import relay as R
from automations.icd_alerts.test_code_answer import Book, Sheet

TZ = dt.timezone(dt.timedelta(hours=-4))
NOW = dt.datetime(2026, 10, 29, 12, 30, 0, tzinfo=TZ)


def setUpModule():
    # Tests must never overwrite the real clipboard of whoever runs them.
    p = mock.patch.object(CF, "_copy")
    p.start()
    unittest.addModuleCleanup(p.stop)


class FakeAsk:
    class Cancelled(Exception):
        pass

    def __init__(self, pick, typed=""):
        self.pick, self.typed, self.shown = pick, typed, []

    def message(self, body, **_):
        self.shown.append(body)

    def choose(self, prompt, options):
        if self.pick is None:
            raise self.Cancelled()
        return self.pick

    def text(self, prompt):
        return self.typed


class OnTheMac(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(CF, "MARK_PATH", Path(tmp.name) / "fwd.txt")
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(CF.C, "creds", return_value={"email": "owner@gmail.com"})
        p.start()
        self.addCleanup(p.stop)
        self.opened = []
        p = mock.patch.object(CF, "_open", side_effect=lambda u, s=None: self.opened.append(u))
        p.start()
        self.addCleanup(p.stop)
        self.sent = []
        p = mock.patch.object(R, "report_forward",
                              side_effect=lambda a, **k: self.sent.append(a) or True)
        p.start()
        self.addCleanup(p.stop)

    def _go(self, ask):
        return CF.walk_through(ask, say=lambda *_: None)

    def test_the_login_email_is_offered_and_sent(self):
        ask = FakeAsk(CF.YES)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.sent, ["owner@gmail.com"])
        self.assertIn("alphaletereporting@gmail.com", ask.shown[0])
        self.assertTrue(CF.already_set_up())

    def test_gmail_opens_on_forwarding_and_the_filter_can_follow(self):
        ask = FakeAsk(CF.YES)
        picks = iter([CF.YES, CF.FILTER_NOW])
        ask.choose = lambda prompt, options: next(picks)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.opened, [CF.FORWARDING_URL, CF.FILTER_URL])

    def test_a_different_address_is_typed(self):
        self.assertEqual(self._go(FakeAsk(CF.OTHER, "codes@office.com")), "done")
        self.assertEqual(self.sent, ["codes@office.com"])

    def test_skip_or_cancel_sends_nothing_and_asks_again(self):
        for ask in (FakeAsk(CF.LATER), FakeAsk(None), FakeAsk(CF.OTHER, "nope")):
            self.assertEqual(self._go(ask), "skipped for now")
        self.assertEqual(self.sent, [])
        self.assertFalse(CF.already_set_up())


class RealReportForward(unittest.TestCase):
    def test_sends_the_address_on_the_fault_road(self):
        import json
        rec = {"office_key": "luke", "relay_key": "k", "relay_url": "u"}
        posted = []
        with mock.patch.object(R, "_endpoint", return_value=rec), \
             mock.patch.object(R, "_post",
                               side_effect=lambda u, b: posted.append(json.loads(b))
                               or '{"ok": true}'):
            self.assertTrue(R.report_forward("owner@gmail.com"))
        fault = posted[0]["fault"]
        self.assertEqual(fault["stage"], CA.FORWARD_STAGE)
        self.assertEqual(CA.address_of(fault["summary"]), "owner@gmail.com")


def fwd_row(office, address):
    row = [""] * (P.F_POSTED + 1)
    row[P.F_OFFICE], row[P.F_DAY], row[P.F_STAGE] = office, "2026-10-29", CA.FORWARD_STAGE
    row[P.F_SUMMARY] = CA.forward_summary(address)
    return row


class OnLucy1(unittest.TestCase):
    def setUp(self):
        self.told = []

    def _run(self, book, send=True):
        return CA.record_forwards(book, send=send, now=NOW, tell=self.told.append,
                                  log=lambda *_: None)

    def test_a_new_office_gets_a_row_with_no_message(self):
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "l@gmail.com")])})
        self.assertEqual(self._run(book), [{"office": "luke", "status": "recorded"}])
        self.assertEqual(book.tabs[CA.MAIL_TAB].rows[-1][:2], ["luke", "l@gmail.com"])
        self.assertIn("recorded", book.tabs[P.FAULTS_TAB].cells[(2, P.F_POSTED + 1)])
        self.assertEqual(self.told, [])

    def test_a_second_setup_replaces_the_address(self):
        mail = Sheet([CA.MAIL_HEADER, ["luke", "old@gmail.com", "", ""]])
        updates = []
        mail.update = lambda rng, vals: updates.append((rng, vals))
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "new@gmail.com")]),
                     CA.MAIL_TAB: mail})
        self._run(book)
        self.assertEqual(updates[0][0], "A2:D2")
        self.assertEqual(updates[0][1][0][:2], ["luke", "new@gmail.com"])
        self.assertEqual(len(mail.rows), 2, "no second row")

    def test_a_dry_run_writes_and_tells_nothing(self):
        book = Book({P.FAULTS_TAB: Sheet([["head"], fwd_row("luke", "l@gmail.com")])})
        self._run(book, send=False)
        self.assertNotIn(CA.MAIL_TAB, book.tabs)
        self.assertEqual(self.told, [])

    def test_the_poster_leaves_forwards_for_record_forwards(self):
        self.assertIn('"probe-code-forward"', inspect.getsource(P.notify_faults))


class TheTerminalLine(unittest.TestCase):
    """docs/sara-forward.html: the same line twice -- forwarding, then filter."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(CF, "MARK_PATH", Path(tmp.name) / "fwd.txt")
        p.start()
        self.addCleanup(p.stop)
        self.opened = []
        p = mock.patch.object(CF, "_open", side_effect=lambda u, s=None: self.opened.append(u))
        p.start()
        self.addCleanup(p.stop)

    def test_first_run_opens_forwarding_then_second_opens_the_filter(self):
        with mock.patch.object(CF, "walk_through",
                               side_effect=lambda a, s: CF._mark("o@gmail.com") or "done"),              mock.patch("automations.icd_alerts.dialogs.message"),              mock.patch("builtins.print"):
            self.assertEqual(CF.main(), 0)
            self.assertEqual(self.opened, [], "walk_through opens Gmail itself")
            self.assertEqual(CF.main(), 0)
        self.assertEqual(self.opened[-1], CF.FILTER_URL)

    def test_a_skip_says_not_yet(self):
        with mock.patch.object(CF, "walk_through", return_value="skipped for now"),              mock.patch("builtins.print"):
            self.assertEqual(CF.main(), 1)
        self.assertFalse(CF.already_set_up())


REAL_MAIL = """someone@gmail.com has requested to automatically forward mail to your email
address alphaletereporting@gmail.com.

To allow someone@gmail.com to automatically forward mail to your address,
please click the link below to confirm the request:

https://mail-settings.google.com/mail/vf-CONFIRM

If you accidentally
clicked the link, but you do not want to allow someone@gmail.com to
automatically forward messages to your address, click this link to cancel this
verification:
https://mail-settings.google.com/mail/uf-CANCEL
"""


class OnlySaraPlusIsForwarded(unittest.TestCase):
    def test_the_steps_warn_off_the_whole_inbox_switch(self):
        self.assertIn("Disable forwarding", CF.STEPS)
        self.assertIn("whole inbox", CF.STEPS)

    def test_the_filter_is_from_saraplus_only(self):
        self.assertIn(CF.SARAPLUS_SENDER, CF.FILTER_STEPS)
        self.assertIn("security.info%40saraplus.com", CF.FILTER_URL)

    def test_the_pages_say_it_too(self):
        root = Path(__file__).resolve().parents[2] / "docs"
        page = (root / "sara-forward.html").read_text(encoding="utf-8")
        self.assertIn("Disable forwarding", page)
        self.assertIn("whole inbox", page)


class OfferedAfterTheHandSignIn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, attr, value in (
                (CF, "MARK_PATH", Path(tmp.name) / "fwd.txt"),
                (CF.C, "install", lambda: {"office_key": "rashad"})):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(CF, "walk_through", return_value="done")
        self.walk = p.start()
        self.addCleanup(p.stop)

    def _ask(self):
        ask = mock.Mock()
        ask.Cancelled = FakeAsk.Cancelled
        return ask

    def test_goes_straight_to_the_steps_with_no_way_to_decline(self):
        ask = self._ask()
        self.assertEqual(CF.offer_after_signin(ask, say=lambda *_: None), "done")
        ask.choose.assert_not_called()
        ask.message.assert_called_once_with(CF.OFFER)
        self.assertIs(self.walk.call_args.kwargs["can_skip"], False)

    def test_already_set_up_is_never_asked(self):
        CF.MARK_PATH.write_text("x")
        ask = self._ask()
        self.assertEqual(CF.offer_after_signin(ask, say=lambda *_: None), "not asked")
        ask.message.assert_not_called()

    def test_an_office_on_texts_is_never_asked(self):
        ask = self._ask()
        with mock.patch.object(CF.C, "install", lambda: {"office_key": "eveliz"}):
            self.assertEqual(CF.offer_after_signin(ask, say=lambda *_: None), "not asked")
        ask.message.assert_not_called()

    def test_a_broken_dialog_never_raises(self):
        ask = self._ask()
        ask.message.side_effect = RuntimeError("no display")
        self.assertEqual(CF.offer_after_signin(ask, say=lambda *_: None), "skipped")


class NoSkipAfterTheHandSignIn(unittest.TestCase):
    def _run(self, **kw):
        ask = mock.Mock()
        ask.Cancelled = FakeAsk.Cancelled
        ask.choose.return_value = CF.YES
        with mock.patch.object(CF, "_open"), \
                mock.patch.object(CF, "_login_email", return_value="a@b.com"), \
                mock.patch.object(CF, "_mark"), \
                mock.patch("automations.icd_alerts.relay.report_forward", return_value=True):
            got = CF.walk_through(ask, say=lambda *_: None, **kw)
        return got, ask

    def test_no_skip_button_and_the_filter_step_always_opens(self):
        got, ask = self._run(can_skip=False)
        self.assertEqual(got, "done")
        ask.choose.assert_called_once()
        self.assertEqual(ask.choose.call_args.args[1], [CF.YES, CF.OTHER])
        ask.message.assert_any_call(CF.WAIT_FOR_CONFIRM)
        ask.message.assert_any_call(CF.FILTER_STEPS)

    def test_our_address_is_copied_and_named_before_gmail_opens(self):
        self._run(can_skip=False)
        CF._copy.assert_called_with(CF.REPORTING_INBOX, mock.ANY)
        self.assertIn(CF.REPORTING_INBOX, CF.STEPS)
        self.assertIn("PASTE", CF.STEPS)
        self.assertIn(CF.REPORTING_INBOX, CF.FILTER_STEPS)

    def test_the_filter_link_opens_the_filter_box(self):
        self.assertIn("#create-filter/from=", CF.FILTER_URL)

    def test_setup_keeps_its_skip_button(self):
        _, ask = self._run()
        self.assertIn(CF.LATER, ask.choose.call_args_list[0].args[1])


class LucyAcceptsGmailsMail(unittest.TestCase):
    def setUp(self):
        self.told, self.accepted = [], []

    def _book(self, added=NOW - dt.timedelta(minutes=2), note="from setup",
              address="owner@gmail.com"):
        self.sheet = Sheet([CA.MAIL_HEADER,
                            ["rashad", address, added.isoformat(), note]])
        return Book({CA.MAIL_TAB: self.sheet})

    def _go(self, book, found, send=True, accept=None):
        return CA.confirm_forwards(
            book, send=send, now=NOW, mails=lambda: found,
            accept=accept or (lambda l, a: self.accepted.append((l, a))),
            tell=self.told.append, log=lambda *_: None)

    def test_the_link_picked_is_confirm_never_cancel(self):
        self.assertEqual(CA.confirmation_link(REAL_MAIL),
                         "https://mail-settings.google.com/mail/vf-CONFIRM")

    def test_the_requester_comes_from_the_subject(self):
        self.assertEqual(CA.requester_of(
            "(#1) Gmail Forwarding Confirmation - Receive Mail from A.b+c@Gmail.com"),
            "a.b+c@gmail.com")

    def test_an_address_on_the_tab_is_confirmed(self):
        got = self._go(self._book(), {"owner@gmail.com": "https://x/vf"})
        self.assertEqual(got[0]["status"], "confirmed")
        self.assertEqual(self.accepted, [("https://x/vf", "owner@gmail.com")])
        self.assertIn(CA.NOTE_CONFIRMED, self.sheet.cells[(2, 4)])

    def test_anyone_else_asking_to_forward_is_left_alone(self):
        self._go(self._book(), {"stranger@gmail.com": "https://x/vf"})
        self.assertEqual(self.accepted, [])

    def test_already_confirmed_is_not_touched(self):
        mails = mock.Mock(return_value={})
        CA.confirm_forwards(self._book(note="from setup; gmail confirmed"), send=True,
                            now=NOW, mails=mails, log=lambda *_: None)
        mails.assert_not_called()

    def test_an_old_row_costs_no_inbox_read(self):
        mails = mock.Mock(return_value={})
        CA.confirm_forwards(self._book(added=NOW - dt.timedelta(days=3)), send=True,
                            now=NOW, mails=mails, log=lambda *_: None)
        mails.assert_not_called()

    def test_no_mail_after_patience_tells_us_once(self):
        book = self._book(added=NOW - dt.timedelta(minutes=30))
        self._go(book, {})
        self.assertEqual(len(self.told), 1)
        self.sheet.rows[1][3] = self.sheet.cells[(2, 4)]
        self._go(book, {})
        self.assertEqual(len(self.told), 1)

    def test_a_failed_confirm_asks_a_person_once(self):
        def boom(l, a):
            raise ValueError("nope")
        book = self._book()
        self._go(book, {"owner@gmail.com": "https://x/vf"}, accept=boom)
        self.assertEqual(len(self.told), 1)
        self.assertIn("click", self.told[0])
        self.assertIn(CA.NOTE_FAILED, self.sheet.cells[(2, 4)])

    def test_a_dry_run_presses_nothing(self):
        self._go(self._book(), {"owner@gmail.com": "https://x/vf"}, send=False)
        self.assertEqual((self.accepted, self.told, self.sheet.cells), ([], [], {}))


class PressingConfirm(unittest.TestCase):
    LINK = "https://mail-settings.google.com/mail/vf-X"
    ASKS = "Confirmation Please confirm forwarding mail of owner@gmail.com to r@gmail.com ."

    def test_it_posts_after_reading_the_right_page(self):
        calls = []

        def fetch(url, data=None):
            calls.append(data)
            return self.ASKS if data is None else "Confirmation Success!"
        CA.accept_confirmation(self.LINK, "owner@gmail.com", fetch=fetch)
        self.assertEqual(calls, [None, b""])

    def test_another_persons_page_is_never_pressed(self):
        calls = []

        def fetch(url, data=None):
            calls.append(data)
            return self.ASKS
        with self.assertRaises(ValueError):
            CA.accept_confirmation(self.LINK, "other@gmail.com", fetch=fetch)
        self.assertEqual(calls, [None])

    def test_a_foreign_host_is_never_opened(self):
        fetch = mock.Mock()
        with self.assertRaises(ValueError):
            CA.accept_confirmation("https://evil.example/mail/vf", "o@gmail.com", fetch=fetch)
        fetch.assert_not_called()

    def test_still_asking_afterwards_is_a_failure(self):
        with self.assertRaises(ValueError):
            CA.accept_confirmation(self.LINK, "owner@gmail.com",
                                   fetch=lambda u, data=None: self.ASKS)


class TheRealFetchActsLikeABrowser(unittest.TestCase):
    """A small page that behaves like Gmail's: no cookie, no confirmation."""

    def setUp(self):
        seen = self.seen = []

        class Page(http.server.BaseHTTPRequestHandler):
            def _send(self, body, cookie=False):
                self.send_response(200)
                if cookie:
                    self.send_header("Set-Cookie", "S=visit; Path=/")
                self.end_headers()
                self.wfile.write(body.encode())

            def do_GET(self):
                self._send("Please confirm forwarding mail of owner@gmail.com", cookie=True)

            def do_POST(self):
                seen.append(dict(self.headers))
                ok = "S=visit" in self.headers.get("Cookie", "")
                self._send("Confirmation Success!" if ok
                           else "Please confirm forwarding mail of owner@gmail.com")

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:%d/mail/vf-X" % self.server.server_port

    def test_the_press_carries_the_cookie_from_the_read(self):
        fetch = CA._browser_fetch()
        self.assertIn("please confirm", fetch(self.url).lower())
        self.assertIn("Success", fetch(self.url, b""))
        self.assertEqual(self.seen[0]["Referer"], self.url)

    def test_two_visits_do_not_share_a_cookie(self):
        CA._browser_fetch()(self.url)
        self.assertIn("please confirm", CA._browser_fetch()(self.url, b"").lower())


class WideForwardAlarm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.stamp = Path(tmp.name) / "scope.txt"
        self.told = []
        self.sheet = Sheet([CA.MAIL_HEADER,
                            ["rashad", "Owner@gmail.com", NOW.isoformat(), "from setup"]])
        self.book = Book({CA.MAIL_TAB: self.sheet})

    def _go(self, counts, now=NOW, send=True):
        return CA.check_forward_scope(self.book, send=send, now=now, counts=counts,
                                      stamp_path=self.stamp, tell=self.told.append,
                                      log=lambda *_: None)

    def test_the_search_leaves_out_saraplus(self):
        q = CA.scope_query("a@gmail.com")
        self.assertIn("deliveredto:a@gmail.com", q)
        self.assertIn("-from:security.info@saraplus.com", q)

    def test_only_saraplus_mail_is_quiet(self):
        self.assertEqual(self._go(lambda a: {"owner@gmail.com": 0}), [])
        self.assertEqual(self.told, [])

    def test_anything_else_tells_us_with_the_office(self):
        self.assertEqual(self._go(lambda a: {"owner@gmail.com": 12}), [("rashad", 12)])
        self.assertIn("rashad", self.told[0])
        self.assertIn("Disable forwarding", self.told[0])

    def test_it_looks_once_an_hour(self):
        self._go(lambda a: {"owner@gmail.com": 0})
        counts = mock.Mock(return_value={})
        self._go(counts, now=NOW + dt.timedelta(minutes=30))
        counts.assert_not_called()
        self._go(counts, now=NOW + dt.timedelta(minutes=61))
        counts.assert_called_once()

    def test_once_per_office_per_day(self):
        self._go(lambda a: {"owner@gmail.com": 1})
        self.sheet.rows[1][3] = self.sheet.cells[(2, 4)]
        self._go(lambda a: {"owner@gmail.com": 2}, now=NOW + dt.timedelta(hours=2))
        self.assertEqual(len(self.told), 1)

    def test_a_dry_run_tells_and_stamps_nothing(self):
        self._go(lambda a: {"owner@gmail.com": 5}, send=False)
        self.assertEqual(self.told, [])
        self.assertFalse(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
