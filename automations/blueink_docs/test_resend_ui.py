"""The web-app resend -- what it refuses, and what it accepts as proof.

A fake page, because every rule here is a rule about NOT clicking, and the one
click there is mails a real person on their first morning.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.blueink_docs import chase
from automations.blueink_docs import recent_ui as U
from automations.blueink_docs import resend_ui as RU

SENT_ROW = "Sent11/20/26 Nina Vale NV"


class FakeEl:
    def __init__(self, page, pk):
        self.page, self.pk = page, pk

    def inner_text(self):
        return self.page.rows_text

    def click(self):
        self.page.clicked.append(self.pk)
        self.page.on_click(self.pk)


class FakePage:
    """One bundle, its signers, and an event log that only grows on a click."""

    def __init__(self, signers, *, rows_text=SENT_ROW, receipt_on_click=True,
                 detail=True):
        self.signers = signers              # [{pk, text, resend}]
        self.rows_text = rows_text
        self.receipt_on_click = receipt_on_click
        self.detail = detail
        self.clicked, self.keys = [], []
        self.log_lines = ["11/20/26 Signing link <aaa> sent via email to %s at %s"
                          % (s.get("who", ""), s.get("addr", ""))
                          for s in signers if s.get("addr")]
        self.waited = 0

    # --- the bits resend_ui uses
    def inner_text(self, sel):
        if sel == RU.DETAIL_SEL:
            if not self.detail:
                raise RuntimeError("no detail panel")
            return " ".join(["Created 11/20/26 Reminders Disabled Signers"]
                            + [s["text"] for s in self.signers]
                            + ["Event Log"] + self.log_lines)
        return "Showing 1 of 1 " + self.rows_text

    def query_selector(self, sel):
        if sel == RU.DETAIL_SEL:
            return FakeEl(self, "detail") if self.detail else None
        for s in self.signers:
            if s["pk"] in sel and s.get("resend", True):
                return FakeEl(self, s["pk"])
        return None

    def query_selector_all(self, sel):
        if sel == RU.BUNDLE_SEL:
            return [FakeEl(self, "row")]
        return []

    def evaluate(self, js, arg=None):
        return [{"pk": s["pk"], "text": s["text"], "resend": s.get("resend", True)}
                for s in self.signers]

    def wait_for_timeout(self, ms):
        self.waited += ms

    @property
    def keyboard(self):
        page = self

        class K:
            def press(self, key):
                page.keys.append(key)
        return K()

    def on_click(self, pk):
        if pk == "row" or not self.receipt_on_click:
            return
        who = [s for s in self.signers if s["pk"] == pk]
        if who and who[0].get("addr"):
            self.log_lines.append(
                "11/24/26 Signing link <bbb> sent via email to %s at %s"
                % (who[0].get("who", ""), who[0]["addr"]))


def _signer(pk, who, addr, status="Sent", resend=True):
    return {"pk": pk, "who": who, "addr": addr, "resend": resend,
            "text": "Employee:%s %s%s" % (who, status, addr)}


@pytest.fixture(autouse=True)
def _no_real_dashboard(monkeypatch):
    """The dashboard load and the search box are `recent_ui`'s, already tested
    there. Stubbed so these tests are about the resend rules alone."""
    monkeypatch.setattr(U, "open_dashboard", lambda page, **kw: None)
    monkeypatch.setattr(U, "_search", lambda page, term: "")
    monkeypatch.setattr(RU, "_settle", lambda page: "")


class TestItRefusesRatherThanGuessing:
    """The opposite direction from recent_ui: there, anything unclassifiable
    BLOCKS a send. Here, anything unclassifiable refuses to send."""

    def test_a_signer_who_has_signed_is_not_reminded(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com", status="Completed")])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert page.clicked == ["row"], page.clicked
        assert any("already signed" in s for s in said), said

    def test_somebody_not_on_the_bundle_is_not_reminded(self):
        page = FakePage([_signer("nub-signerPk-1", "Someone Else",
                                 "else@example.com")])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert page.clicked == ["row"]
        assert any("not a signer" in s for s in said), said

    def test_an_unreadable_status_is_not_reminded(self):
        bad = _signer("nub-signerPk-1", "Nina Vale", "nv@example.com")
        bad["text"] = "Employee:Nina Vale nv@example.com"
        page = FakePage([bad])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert any("could not read" in s for s in said), said

    def test_no_resend_control_is_not_reminded(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com", resend=False)])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert any("no Resend" in s for s in said), said

    def test_a_draft_only_bundle_is_not_opened(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")],
                        rows_text="Draft11/20/26 Nina Vale NV")
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert page.clicked == [], "a draft row must not be opened"
        assert any("no live Blue Ink packet" in s for s in said), said

    def test_no_address_sends_nothing(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")])
        assert RU.resend(page, "Nina Vale", "", dry_run=False,
                         log=lambda *a: None) is False
        assert page.clicked == []


class TestTheEventLogIsTheProof:
    """exit-0 is not green ([[feedback_green_means_delivered]]). The click is a
    request; the log line is the app saying it happened."""

    def test_a_new_receipt_is_what_makes_it_true(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is True
        assert "nub-signerPk-1" in page.clicked
        assert any("event log says" in s for s in said), said

    def test_a_click_with_no_new_receipt_is_reported_as_not_sent(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")], receipt_on_click=False)
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=said.append) is False
        assert "nub-signerPk-1" in page.clicked
        assert any("never said it went" in s for s in said), said

    def test_the_first_sends_receipt_is_not_mistaken_for_this_one(self):
        """The log already holds a line for the original send."""
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")], receipt_on_click=False)
        assert RU._receipts(page, "nv@example.com") == 1
        RU.resend(page, "nv@example.com", "nv@example.com", dry_run=False,
                  log=lambda *a: None)
        assert RU._receipts(page, "nv@example.com") == 1


class TestItClicksTheRightSignersResend:
    def test_a_multi_signer_bundle_resends_only_to_the_one_asked_for(self):
        page = FakePage([_signer("nub-signerPk-1", "Already Done",
                                 "done@example.com", status="Completed"),
                         _signer("nub-signerPk-2", "Nina Vale",
                                 "nv@example.com")])
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=False, log=lambda *a: None) is True
        assert "nub-signerPk-2" in page.clicked
        assert "nub-signerPk-1" not in page.clicked


class TestADryRunClicksNothing:
    def test_it_reads_and_refuses_to_claim_a_send(self):
        page = FakePage([_signer("nub-signerPk-1", "Nina Vale",
                                 "nv@example.com")])
        said = []
        assert RU.resend(page, "nv@example.com", "nv@example.com",
                         dry_run=True, log=said.append) is False
        assert page.clicked == ["row"], "only the row was opened"
        assert any("would re-send" in s for s in said), said


class TestTheModalIsClosedOnEveryPath:
    """The detail opens over a dimmer; left open, the NEXT person's row click
    lands on the overlay and retries for thirty seconds."""

    @pytest.mark.parametrize("signer", [
        _signer("nub-signerPk-1", "Nina Vale", "nv@example.com"),
        _signer("nub-signerPk-1", "Nina Vale", "nv@example.com",
                status="Completed"),
        _signer("nub-signerPk-1", "Someone Else", "else@example.com"),
    ])
    def test_escape_is_pressed(self, signer):
        page = FakePage([signer])
        RU.resend(page, "nv@example.com", "nv@example.com", dry_run=False,
                  log=lambda *a: None)
        assert "Escape" in page.keys


class TestTheChasePicksTheRouteByWhetherThereIsAKey:
    """Megan, 2026-11-23: "assume that every ICD isn't going to have an API"."""

    def _person(self):
        class P:
            first, last, email = "Nicolas", "Vargas", "nv@example.com"
        return P()

    def test_a_dry_run_counts_only_what_the_screen_approved(self, monkeypatch):
        monkeypatch.setattr(RU, "inspect",
                            lambda page, term, email, **kw:
                            (RU.WOULD_SEND, {"status": "sent"}, "row"))
        monkeypatch.setattr("automations.blueink_docs.chase_email.send",
                            lambda *a, **k: "would email")
        assert chase._remind_in_the_app(
            _NullSession(), "nv@example.com", "Nina Vale", "day-before",
            dt.date(2026, 11, 25), send=False, log=lambda *a: None) is True

    def test_a_dry_run_does_not_claim_a_remind_for_somebody_who_signed(
            self, monkeypatch):
        """The 2026-11-24 fault: eleven people, all signed, all "would remind"."""
        said = []
        monkeypatch.setattr(RU, "inspect",
                            lambda page, term, email, **kw:
                            (RU.SIGNED, None, "row"))
        assert chase._remind_in_the_app(
            _NullSession(), "nv@example.com", "Nina Vale", "day-before",
            dt.date(2026, 11, 25), send=False, log=said.append) is False
        assert any("already signed" in s for s in said), said

    def test_the_resend_searches_the_term_that_found_the_bundle(self, monkeypatch):
        """Approved by NAME, then resent by address, would refuse the person it
        had just approved."""
        monkeypatch.setattr(
            RU, "inspect",
            lambda page, term, email, **kw:
            ((RU.WOULD_SEND, {"status": "sent"}, "row") if term == "Nina Vale"
             else (RU.NOT_A_SIGNER, None, "row")))
        used = {}
        monkeypatch.setattr(RU, "resend",
                            lambda page, term, email, **kw:
                            used.setdefault("term", term) or True)
        assert chase._remind_in_the_app(
            _NullSession(), "nv@example.com", "Nina Vale", "day-before",
            dt.date(2026, 11, 25), send=True, log=lambda *a: None) is True
        assert used["term"] == "Nina Vale"

    def test_the_api_route_needs_a_key_of_its_own(self):
        """Not a mock: the helper itself asks blueink, which raises with no key."""
        import inspect
        src = inspect.getsource(chase.run)
        assert "config.using_own_key()" in src
        assert "_remind_in_the_app" in src
        assert src.index("config.using_own_key()") < src.index("_remind_in_the_app")


class _NullSession:
    page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestTheRealSignerLines:
    """The SHAPE of the live app's signer lines, read 2026-11-24.

    Invented names and example.com addresses. The shape is the whole point of
    this test and real applicants' addresses are not ours to put in a public
    repository -- the status running into the local part with no separator is
    what it pins, and that survives the substitution.

    Every character of "Sent" is legal in an email local part, so an address
    regex on its own returns `Sentnvargas@example.net` -- which matches
    nobody, and the chase then refuses the right person with the words "not a
    signer on this bundle".
    """

    LIVE = [
        ("Employee:Marla Wren Startedmwilliams099@example.com",
         "started", "mwilliams099@example.com"),
        ("Employee:Nina Vale Sentnvargas@example.net",
         "sent", "nvargas@example.net"),
        ("Employee:Liam Frost Sentlfrias8089@example.com",
         "sent", "lfrias8089@example.com"),
        ("Employee:Hana Ark Senthakkad87@example.com",
         "sent", "hakkad87@example.com"),
        ("Employee:Jane Doe Completedjane.doe+hr@example.co.uk",
         "completed", "jane.doe+hr@example.co.uk"),
    ]

    def test_each_one_reads_as_a_status_and_an_address(self):
        class P:
            def evaluate(self, js, arg=None):
                return [{"pk": "nub-signerPk-%d" % i, "text": t,
                         "resend": True}
                        for i, (t, _, _) in enumerate(
                            TestTheRealSignerLines.LIVE)]
        got = RU.signers(P())
        assert [(g["status"], g["email"]) for g in got] == \
            [(s, e) for _, s, e in self.LIVE]

    def test_completed_before_complete_in_the_alternation(self):
        """"Complete" first would leave the "d" on the front of the address."""
        class P:
            def evaluate(self, js, arg=None):
                return [{"pk": "nub-signerPk-1", "resend": True,
                         "text": "Employee:X Completedx@example.com"}]
        assert RU.signers(P())[0]["email"] == "x@example.com"


class TestTheSecondSearchDoesNotOverwriteABetterAnswer:
    """Hattie Pell, 2026-11-24: her ADDRESS found `Complete11/23/26 Hattie Pell`,
    her roster name is the corrupt "Hattie `", and the retry by name found
    nothing -- so the chase reported "no live Blue Ink packet" about a packet
    she had signed."""

    def _asked(self, monkeypatch, answers):
        seen = []

        def fake(page, term, email, **kw):
            seen.append(term)
            return answers.get(term, (RU.NO_PACKET, None, ""))
        monkeypatch.setattr(RU, "inspect", fake)
        return seen

    def test_already_signed_is_not_retried_away(self, monkeypatch):
        seen = self._asked(monkeypatch, {
            "hpaul0715@example.com": (RU.SIGNED, None, "Complete11/23/26"),
        })
        said = []
        assert chase._remind_in_the_app(
            _NullSession(), "hpaul0715@example.com", "Hattie `", "morning-of",
            dt.date(2026, 11, 23), send=False, log=said.append) is False
        assert seen == ["hpaul0715@example.com"], "the name must not be asked"
        assert any("already signed" in s for s in said), said

    def test_not_found_by_address_still_tries_the_name(self, monkeypatch):
        seen = self._asked(monkeypatch, {
            "Nina Vale": (RU.WOULD_SEND, {"status": "sent"}, "Sent"),
        })
        monkeypatch.setattr("automations.blueink_docs.chase_email.send",
                            lambda *a, **k: "would email")
        assert chase._remind_in_the_app(
            _NullSession(), "wrong@example.com", "Nina Vale",
            "morning-of", dt.date(2026, 11, 23), send=False,
            log=lambda *a: None) is True
        assert seen == ["wrong@example.com", "Nina Vale"]
