"""Setup asks for the SaraPlus code forward on the spot (code_forward), and
Lucy 1 files the address (code_answer.record_forwards). 2026-10-29.

What must hold: the address the owner picks is the one sent, and sent WITHOUT
the scrub that would blank it; skipping sends nothing and asks again later;
Lucy 1 keeps one row per office. 2026-11-02: only SaraPlus's mail is forwarded,
the steps warn off Gmail's whole-inbox switch, Lucy 1 accepts Gmail's mail only
for an address on the tab, and we hear if an address forwards anything else.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import inspect
import tempfile
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
    # Nor reach the real relay. Tests about it patch this back.
    p = mock.patch.object(R, "forward_working", return_value=False)
    p.start()
    unittest.addModuleCleanup(p.stop)
    p = mock.patch.object(R, "report_fault", return_value=True)
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
        # Not confirmed until the address has gone home, confirmed after.
        p = mock.patch.object(R, "forward_confirmed",
                              side_effect=lambda *a, **k: bool(self.sent))
        self.confirmed = p.start()
        self.addCleanup(p.stop)

    def _go(self, ask):
        return CF.walk_through(ask, say=lambda *_: None)

    def test_the_login_email_is_offered_and_sent(self):
        ask = FakeAsk(CF.YES)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.sent, ["owner@gmail.com"])
        self.assertIn("alphaletereporting@gmail.com", ask.shown[0])
        self.assertIn("owner@gmail.com", ask.shown[0], "names the account to be in")
        self.assertFalse(CF.already_set_up(), "OK on the filter box proves nothing")

    def test_gmail_opens_on_forwarding_and_the_filter_follows(self):
        ask = FakeAsk(CF.YES)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.opened, [CF.for_account(CF.FORWARDING_URL, "owner@gmail.com"), CF.for_account(CF.FILTER_URL, "owner@gmail.com")])

    def test_gmail_opens_in_the_account_the_owner_named(self):
        # Trang: /u/0 went by with nothing reaching us; authuser worked first try.
        self.assertEqual(self._go(FakeAsk(CF.OTHER, "a+b@office.com")), "done")
        self.assertEqual(self.opened[0],
                         "https://mail.google.com/mail/?authuser=a%2Bb@office.com#settings/fwdandpop")
        self.assertIn("/mail/?authuser=a%2Bb@office.com#create-filter/from=", self.opened[1])

    def test_no_address_stays_on_the_default_account(self):
        self.assertEqual(CF.for_account(CF.FILTER_URL, ""), CF.FILTER_URL)

    def test_a_different_address_is_typed(self):
        self.assertEqual(self._go(FakeAsk(CF.OTHER, "codes@office.com")), "done")
        self.assertEqual(self.sent, ["codes@office.com"])

    def test_skip_or_cancel_sends_nothing_and_asks_again(self):
        for ask in (FakeAsk(CF.LATER), FakeAsk(None), FakeAsk(CF.OTHER, "nope")):
            self.assertEqual(self._go(ask), "skipped for now")
        self.assertEqual(self.sent, [])
        self.assertFalse(CF.already_set_up())

    def _never_confirmed(self):
        self.confirmed.side_effect = lambda *a, **k: False
        return mock.patch.multiple(CF, CONFIRM_WAIT_S=0, CONFIRM_POLL_S=0)

    def test_ok_without_gmail_is_not_done_and_it_comes_back(self):
        # Isaiah, Jamis, Trang: OK pressed, no confirmation ever reached us.
        ask = FakeAsk(CF.YES)
        with self._never_confirmed():
            self.assertEqual(self._go(ask), "not confirmed yet")
        self.assertFalse(CF.already_set_up())
        self.assertNotIn(CF.for_account(CF.FILTER_URL, "owner@gmail.com"), self.opened)
        self.assertEqual(ask.shown[-1], CF.LEFT_OPEN)
        self.assertTrue(any("owner@gmail.com" in m and "heard from Gmail" in m
                            for m in ask.shown), "says what to check, by account")
        self.assertEqual(self.sent, ["owner@gmail.com"], "sent home once")

    def test_a_second_try_that_works_goes_on_to_the_filter(self):
        answers = iter([False, False, True])
        self.confirmed.side_effect = lambda *a, **k: next(answers, True)
        ask = FakeAsk(CF.YES)
        with mock.patch.multiple(CF, CONFIRM_WAIT_S=0, CONFIRM_POLL_S=0):
            # The check at the top and the first wait say no, the second yes.
            self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.opened, [CF.for_account(CF.FORWARDING_URL, "owner@gmail.com")] * 2 + [CF.for_account(CF.FILTER_URL, "owner@gmail.com")])
        self.assertEqual(self.sent, ["owner@gmail.com"])

    def test_already_confirmed_skips_straight_to_the_filter(self):
        # Luke, Valeria, Carlos: the address is in, only the filter is left.
        self.confirmed.side_effect = lambda *a, **k: True
        ask = FakeAsk(CF.YES)
        self.assertEqual(self._go(ask), "done")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.opened, [CF.for_account(CF.FILTER_URL, "owner@gmail.com")])
        self.assertFalse(CF.already_set_up())

    def test_ok_on_the_filter_without_a_code_comes_back(self):
        # Luke: address confirmed, no code ever reached us. Each hand sign-in
        # shows the filter again until one does.
        self.confirmed.side_effect = lambda *a, **k: True
        with mock.patch.object(CF.C, "install", return_value={"office_key": "luke"}):
            for _ in range(2):
                self.opened.clear()
                CF.offer_after_signin(FakeAsk(CF.YES), say=lambda *_: None)
                self.assertEqual(self.opened, [CF.for_account(CF.FILTER_URL, "owner@gmail.com")])

    def test_a_code_that_arrived_ends_the_asking_for_good(self):
        self.confirmed.side_effect = lambda *a, **k: True
        with mock.patch.object(CF.C, "install", return_value={"office_key": "luke"}), \
                mock.patch.object(R, "forward_working", return_value=True):
            CF.offer_after_signin(FakeAsk(CF.YES), say=lambda *_: None)
        self.assertEqual(self.opened, [])
        self.assertTrue(CF.already_set_up())
        with mock.patch.object(CF.C, "install", return_value={"office_key": "luke"}):
            self.assertEqual(CF.offer_after_signin(FakeAsk(CF.YES), say=lambda *_: None),
                             "not asked")

    def test_a_cancelled_filter_is_not_done(self):
        self.confirmed.side_effect = lambda *a, **k: True
        ask = FakeAsk(CF.YES)
        ask.message = mock.Mock(side_effect=FakeAsk.Cancelled())
        self.assertEqual(self._go(ask), "filter not shown")
        self.assertFalse(CF.already_set_up())

    def test_an_old_premature_mark_counts_for_nothing(self):
        # What brings the offices that stopped halfway back, with no message.
        # Both older names were written on a press of OK.
        real = inspect.getsource(CF).split('MARK_PATH = C.APP_DIR / "')[1].split('"')[0]
        self.assertEqual(real, "sara-code-forward-working.txt")


class TheWaitBeforeTheFilter(OnTheMac):
    """Eve 2026-11-04: nothing on screen during the wait, ALL SET already read."""

    def test_a_box_is_up_while_lucy_checks(self):
        held = []
        ask = FakeAsk(CF.YES)
        ask.hold = lambda body, seconds: held.append((body, seconds))
        self.confirmed.side_effect = [False, False, True]
        with mock.patch.object(CF, "CONFIRM_POLL_S", 0):
            self.assertEqual(self._go(ask), "done")
        self.assertTrue(held)
        self.assertIn("don't close anything", held[0][0])

    def test_clicking_the_box_away_still_waits_the_whole_pause(self):
        ask = FakeAsk(CF.YES)
        ask.hold = lambda body, seconds: None
        with mock.patch.object(CF.time, "sleep") as slept:
            CF.holding(ask)(15)
        self.assertGreater(slept.call_args.args[0], 14)

    def test_a_box_that_runs_its_time_does_not_add_more(self):
        clock = iter([100.0, 115.0])
        ask = FakeAsk(CF.YES)
        ask.hold = lambda body, seconds: None
        with mock.patch.object(CF.time, "time", lambda: next(clock)), \
             mock.patch.object(CF.time, "sleep") as slept:
            CF.holding(ask)(15)
        slept.assert_not_called()

    def test_each_step_is_written_down(self):
        R.report_fault.reset_mock()
        self.assertEqual(self._go(FakeAsk(CF.YES)), "done")
        said = [c.args[1] for c in R.report_fault.call_args_list]
        for word in ("gmail steps closed", "gmail confirmed", "filter box closed"):
            self.assertTrue(any(word in s for s in said), word)
        self.assertEqual({c.args[0] for c in R.report_fault.call_args_list},
                         {CF.STEP_STAGE})

    def test_the_record_is_never_posted_to_anyone(self):
        self.assertTrue(CF.STEP_STAGE.startswith("probe-"))


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


class RealForwardConfirmed(unittest.TestCase):
    """Reads what the relay's _codePoll really answers (resources/icd-alerts-relay.gs)."""

    def _ask(self, reply=None, boom=None):
        rec = {"office_key": "isaiah", "relay_url": "u", "relay_key": "k"}
        post = mock.Mock(return_value=reply, side_effect=boom)
        with mock.patch.object(R, "_endpoint", return_value=rec), \
                mock.patch.object(R, "_post", post):
            return R.forward_confirmed(), post

    def test_a_row_with_no_code_reads_as_taken_is_confirmed(self):
        got, post = self._ask('{"ok": true, "status": "taken"}')
        self.assertTrue(got)
        self.assertIn(CA.FORWARD_STATE, post.call_args.args[1].decode())

    def test_no_row_old_relay_or_no_network_is_not_confirmed(self):
        self.assertFalse(self._ask('{"ok": true, "status": "waiting"}')[0])
        self.assertFalse(self._ask('{"ok": false, "error": "bad day"}')[0])
        self.assertFalse(self._ask(boom=OSError("down"))[0])


class CodesAlreadyReachUs(unittest.TestCase):
    """Eve 2026-11-03: whoever's codes already arrive saves no filter again."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.stamp = Path(tmp.name) / "stamp.txt"
        p = mock.patch.object(CF, "MARK_PATH", Path(tmp.name) / "fwd.txt")
        p.start()
        self.addCleanup(p.stop)
        self.opened = []
        p = mock.patch.object(CF, "_open", side_effect=lambda u, s=None: self.opened.append(u))
        p.start()
        self.addCleanup(p.stop)
        self.sheet = Sheet([CA.MAIL_HEADER,
                            ["Carlos", "a@gmail.com", NOW.isoformat(), "from setup"],
                            ["carlos-b2batt", "a@gmail.com", NOW.isoformat(), ""],
                            ["Luke", "l@gmail.com", NOW.isoformat(), "gmail confirmed"]])
        self.codes = Sheet([CA.CODES_HEADER])
        self.book = Book({CA.MAIL_TAB: self.sheet, CA.CODES_TAB: self.codes})

    def _publish(self, got, send=True, now=NOW):
        asked = mock.Mock(return_value=got)
        out = CA.publish_working(self.book, send=send, now=now, addresses=asked,
                                 stamp_path=self.stamp, log=lambda *_: None)
        return out, asked

    def test_only_an_address_seen_forwarding_is_published_with_no_code(self):
        out, _ = self._publish({"a@gmail.com"})
        self.assertEqual(out, ["carlos", "carlos-b2batt"])
        self.assertEqual(self.codes.rows[-1][:3], ["carlos-b2batt", CA.FORWARD_WORKING_STATE, ""])
        self.assertIn(CA.NOTE_CODES_ARRIVE, self.sheet.cells[(2, 4)])
        self.assertNotIn((4, 4), self.sheet.cells, "no mail proves nothing about Luke")

    def test_a_dry_run_writes_nothing(self):
        self.assertEqual(self._publish({"a@gmail.com"}, send=False)[0], ["carlos", "carlos-b2batt"])
        self.assertEqual(self.codes.rows[1:], [])
        self.assertFalse(self.stamp.exists())

    def test_the_inbox_is_opened_once_an_hour(self):
        self._publish(set())
        self.assertEqual(self._publish(set(), now=NOW + dt.timedelta(minutes=5))[1].call_count, 0)
        self.assertEqual(self._publish(set(), now=NOW + dt.timedelta(minutes=61))[1].call_count, 1)

    def test_with_every_row_stamped_the_inbox_is_not_opened(self):
        self.book = Book({CA.MAIL_TAB: Sheet([CA.MAIL_HEADER,
                                              ["Carlos", "a@gmail.com", "", CA.NOTE_CODES_ARRIVE]])})
        self.assertEqual(self._publish({"a@gmail.com"})[1].call_count, 0)

    def test_a_broken_inbox_never_costs_the_poster_its_tick(self):
        out = CA.publish_working(self.book, send=True, now=NOW, stamp_path=self.stamp,
                                 addresses=mock.Mock(side_effect=OSError("down")),
                                 log=lambda *_: None)
        self.assertEqual(out, [])

    def test_only_x_forwarded_for_counts_and_codes_are_never_opened(self):
        M = mock.Mock()
        M.select.return_value = ("OK", [b"1"])
        M.search.return_value = ("OK", [b"1 2"])
        M.fetch.return_value = ("OK", [(b"1", b"X-Forwarded-For: A@gmail.com reporting@x.com\r\n"),
                                       b")"])
        with mock.patch.object(CA, "_imap", return_value=M):
            got = CA._addresses_forwarding_codes()
        self.assertIn("a@gmail.com", got)
        self.assertEqual(M.select.call_count, len(CA.WORKING_FOLDERS))
        self.assertIn("HEADER.FIELDS (X-FORWARDED-FOR)", M.fetch.call_args.args[1])

    def test_the_mac_asks_nothing_and_opens_nothing(self):
        ask = FakeAsk(CF.YES)
        with mock.patch.object(R, "forward_working", return_value=True), \
                mock.patch.object(R, "forward_confirmed", return_value=True):
            self.assertEqual(CF.walk_through(ask, say=lambda *_: None), "done")
        self.assertEqual(ask.shown, [])
        self.assertEqual(self.opened, [])
        self.assertTrue(CF.already_set_up())

    def test_the_terminal_line_says_all_set_without_the_filter(self):
        said = []
        with mock.patch.object(R, "forward_working", return_value=True), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: said.append(a[0] if a else "")):
            self.assertEqual(CF.main(), 0)
        self.assertEqual(self.opened, [])
        self.assertFalse(any("filter" in l for l in said))
        self.assertTrue(any("ALL SET" in l for l in said))

    def test_the_mac_reads_it_through_the_relay(self):
        rec = {"office_key": "carlos", "relay_url": "u", "relay_key": "k"}
        post = mock.Mock(return_value='{"ok": true, "status": "taken"}')
        with mock.patch.object(R, "_endpoint", return_value=rec), \
                mock.patch.object(R, "_post", post):
            self.assertTrue(R._state_row(CA.FORWARD_WORKING_STATE))
        self.assertIn(CA.FORWARD_WORKING_STATE, post.call_args.args[1].decode())

    def test_the_poster_runs_it(self):
        self.assertIn("code_answer.publish_working(book", inspect.getsource(P))


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

    def test_finished_says_all_set_and_a_rerun_walks_again(self):
        # No code has arrived yet, so the line keeps offering the filter.
        walk = mock.Mock(return_value="done")
        with mock.patch.object(CF, "walk_through", walk), \
                mock.patch.object(R, "forward_working", return_value=False), \
                mock.patch("automations.icd_alerts.dialogs.message"):
            self.assertEqual(CF.main(), 0)
            self.assertEqual(CF.main(), 0)
        self.assertEqual(walk.call_count, 2)

    def test_a_computer_whose_codes_arrived_opens_nothing(self):
        CF._mark("o@gmail.com")
        with mock.patch.object(R, "forward_working", return_value=False), \
                mock.patch("builtins.print"):
            self.assertEqual(CF.main(), 0)
        self.assertEqual(self.opened, [])

    def test_stopped_halfway_says_not_yet(self):
        with mock.patch.object(CF, "walk_through", return_value="not confirmed yet"), \
                mock.patch("automations.icd_alerts.dialogs.message"):
            self.assertEqual(CF.main(), 1)
        self.assertFalse(CF.already_set_up())

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
        ask.message.assert_not_called()
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
        self.walk.side_effect = RuntimeError("no display")
        self.assertEqual(CF.offer_after_signin(self._ask(), say=lambda *_: None), "skipped")


class NoSkipAfterTheHandSignIn(unittest.TestCase):
    def _run(self, **kw):
        ask = mock.Mock()
        ask.Cancelled = FakeAsk.Cancelled
        ask.choose.return_value = CF.YES
        with mock.patch.object(CF, "_open"), \
                mock.patch.object(CF, "_login_email", return_value="a@b.com"), \
                mock.patch.object(CF, "_mark"), \
                mock.patch("automations.icd_alerts.relay.forward_confirmed",
                           side_effect=[False, True]), \
                mock.patch("automations.icd_alerts.relay.report_forward", return_value=True):
            got = CF.walk_through(ask, say=lambda *_: None, **kw)
        return got, ask

    def test_no_skip_button_and_the_filter_step_always_opens(self):
        got, ask = self._run(can_skip=False)
        self.assertEqual(got, "done")
        ask.choose.assert_called_once()
        self.assertEqual(ask.choose.call_args.args[1], [CF.YES, CF.OTHER])
        self.assertIn(CF.OFFER, ask.choose.call_args.args[0], "reason + question, one box")
        ask.message.assert_any_call(CF.FILTER_STEPS)
        self.assertEqual(ask.message.call_count, 2, "steps + filter: three clicks in all")

    def test_our_address_is_copied_and_named_before_gmail_opens(self):
        self._run(can_skip=False)
        CF._copy.assert_called_with(CF.REPORTING_INBOX, mock.ANY)
        self.assertIn(CF.REPORTING_INBOX, CF.STEPS % (CF.REPORTING_INBOX, "a@b.com"))
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
        CA.confirm_forwards(self._book(added=NOW - dt.timedelta(days=CA.CONFIRM_WINDOW_DAYS + 1)),
                            send=True, now=NOW, mails=mails, log=lambda *_: None)
        mails.assert_not_called()

    def test_coming_back_days_later_still_gets_confirmed(self):
        got = self._go(self._book(added=NOW - dt.timedelta(days=5)),
                       {"owner@gmail.com": "https://x/vf"})
        self.assertEqual(got[0]["status"], "confirmed")

    def test_a_row_past_its_first_hour_is_read_every_ten_minutes(self):
        book = self._book(added=NOW - dt.timedelta(days=5))
        mails = mock.Mock(return_value={})
        at = NOW.replace(minute=33)
        CA.confirm_forwards(book, send=True, now=at, mails=mails, log=lambda *_: None)
        mails.assert_not_called()
        CA.confirm_forwards(book, send=True, now=at.replace(minute=40), mails=mails,
                            tell=self.told.append, log=lambda *_: None)
        mails.assert_called_once()

    def test_a_second_row_on_a_confirmed_address_is_confirmed_without_pressing(self):
        added = (NOW - dt.timedelta(minutes=2)).isoformat()
        sheet = Sheet([CA.MAIL_HEADER,
                       ["carlos", "a@gmail.com", added, "from setup; gmail confirmed"],
                       ["carlos-b2batt", "a@gmail.com", added, "from setup"]])
        self._go(Book({CA.MAIL_TAB: sheet}), {"a@gmail.com": "https://x/vf"})
        self.assertEqual(self.accepted, [])
        self.assertEqual(self.told, [])
        self.assertIn(CA.NOTE_CONFIRMED, sheet.cells[(3, 4)])

    def test_an_office_on_texts_is_never_waited_on(self):
        sheet = Sheet([CA.MAIL_HEADER,
                       ["eveliz", "e@gmail.com",
                        (NOW - dt.timedelta(hours=30)).isoformat(), "from setup"]])
        self._go(Book({CA.MAIL_TAB: sheet}), {})
        self.assertEqual(self.told, [])

    def _publish(self, note, send=True):
        self.sheet = Sheet([CA.MAIL_HEADER, ["Rashad", "o@gmail.com", NOW.isoformat(), note]])
        self.codes = Sheet([CA.CODES_HEADER])
        book = Book({CA.MAIL_TAB: self.sheet, CA.CODES_TAB: self.codes})
        return CA.publish_confirmed(book, send=send, now=NOW, log=lambda *_: None)

    def test_a_confirmed_row_is_published_once_with_no_code(self):
        self.assertEqual(self._publish("from setup; gmail confirmed (by hand, Eve)"), ["rashad"])
        row = self.codes.rows[-1]
        self.assertEqual(row[:3], ["rashad", CA.FORWARD_STATE, ""])
        self.assertEqual(row[5], "", "a status of none would read as no forward")
        self.assertIn(CA.NOTE_MAC_TOLD, self.sheet.cells[(2, 4)])
        self.assertEqual(self._publish("x; gmail confirmed; mac told"), [])

    def test_an_unconfirmed_row_is_never_published(self):
        self.assertEqual(self._publish("from setup; no gmail mail yet"), [])
        self.assertEqual(self.codes.rows[1:], [])

    def test_the_poster_publishes_after_confirming(self):
        src = inspect.getsource(P)
        self.assertLess(src.index("code_answer.confirm_forwards(book"),
                        src.index("code_answer.publish_confirmed(book"))

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


class _FakeGmailPage:
    def __init__(self, before, after):
        self.text, self.after, self.clicks = before, after, []

    def goto(self, url, timeout=None):
        self.url = url

    def inner_text(self, selector):
        return self.text

    @contextlib.contextmanager
    def expect_navigation(self, timeout=None):
        yield

    def click(self, selector):
        self.clicks.append(selector)
        self.text = self.after


class PressingConfirm(unittest.TestCase):
    LINK = "https://mail-settings.google.com/mail/vf-X"
    ASKS = "Confirmation Please confirm forwarding mail of owner@gmail.com to r@gmail.com ."
    DONE = "Confirmation Success! owner@gmail.com may now forward mail to r@gmail.com."

    def _press(self, page, who="owner@gmail.com", link=None):
        @contextlib.contextmanager
        def open_page():
            yield page
        CA.accept_confirmation(link or self.LINK, who, open_page=open_page)

    def test_it_presses_after_reading_the_right_page(self):
        page = _FakeGmailPage(self.ASKS, self.DONE)
        self._press(page)
        self.assertEqual(len(page.clicks), 1)

    def test_another_persons_page_is_never_pressed(self):
        page = _FakeGmailPage(self.ASKS, self.DONE)
        with self.assertRaises(ValueError):
            self._press(page, who="other@gmail.com")
        self.assertEqual(page.clicks, [])

    def test_a_foreign_host_is_never_opened(self):
        opened = mock.Mock()
        with self.assertRaises(ValueError):
            CA.accept_confirmation("https://evil.example/mail/vf", "o@gmail.com",
                                   open_page=opened)
        opened.assert_not_called()

    def test_still_asking_afterwards_is_a_failure(self):
        with self.assertRaises(ValueError):
            self._press(_FakeGmailPage(self.ASKS, self.ASKS))

    def test_only_the_success_page_counts(self):
        with self.assertRaises(ValueError):
            self._press(_FakeGmailPage(self.ASKS, "Something went wrong"))


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
