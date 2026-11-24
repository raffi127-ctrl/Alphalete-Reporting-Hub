"""Re-send one signer's invitation -- through the WEB APP, no API key.

WHY THIS EXISTS. `chase.py` reminds through `blueink.remind_packet`, which
needs a private API key, and API Access is an Enterprise-only feature on this
plan: on 2026-08-24 no machine in the fleet had a key, and Megan's direction on
2026-11-23 is to assume no ICD ever will --

    "We need to just assume that every ICD isn't going to have an API ... and
    that we need to work Blueink without it."

So the chase had exactly one route and it was the route nobody can use. This is
the second one, against the same screen a person would use, the way
`recent_ui` already reads the dashboard for the duplicate check.

THE SCREEN (mapped against the live app 2026-11-24)

  A row in the Sent or Started column is `[data-tid=nub-bundle]`. Clicking it
  opens `[data-tid=nub-bundleDetail]` as a MODAL over a dimmer -- so the next
  row click lands on the overlay, not the row, until Escape closes it. That is
  not cosmetic: without the close, the second bundle of any loop retries its
  click for thirty seconds and then fails.

  Inside, each signer is `[data-tid=nub-signerPk-<id>]`, and the resend is
  `[data-tid=nub-sendText]` ("Resend") within that signer's own block. PER
  SIGNER, which is what this needs: a bundle reads "Started" the moment one of
  several signers finishes, and a bundle-level resend would mail the ones who
  already signed.

  A signer's line reads `Employee:Nina Vale Sentnvargas@example.net` --
  the status and the address run together with no separator, which is why
  `_SIGNER_RE` reads them as one match rather than splitting on whitespace.

  The Event Log carries `Signing link <urQOYffq> sent via email to Nicolas
  Vargas at nvargas@example.net`. That is a RECEIPT, and this waits for a
  new one rather than treating the click as proof ([[feedback_green_means_delivered]]).

WHICH WAY TO BE WRONG. The opposite way from `recent_ui`. There, anything
unclassifiable blocks, because the cost is a duplicate contract packet. Here
the click mails a real person on their first morning, so anything
unclassifiable REFUSES: a signer whose status cannot be read, a bundle that
cannot be found, a page that will not settle. A chase that did not go is a
missing nudge; a chase that went to somebody who already signed is the one
thing Megan's card says never to do.

WHAT THIS WILL NOT DO
  * resend to a signer whose packet reads completed, complete or signed;
  * resend twice in one call, or without reading the Event Log afterwards;
  * create, cancel, void or edit anything. The only control it clicks is
    Resend, and the only other key it presses is Escape.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from automations.blueink_docs import recent_ui as U
from automations.blueink_docs import session as S

DETAIL_SEL = "[data-tid='nub-bundleDetail']"
# THE RESEND IS INSIDE A CLOSED DROPDOWN. Its container is `.menu transition
# left` at `display: none`, holding Resend and Edit, and the only thing that
# opens it is the ellipsis (...) button in that signer's row. Clicking Resend
# without opening it first finds the element -- `query_selector` does not care
# about visibility -- and then waits thirty seconds for something 0x0 to
# become clickable before raising (proved on a test bundle 2026-11-24, which
# is the whole reason that bundle was worth sending).
#
# No data-tid on the trigger, so it is found by class within the signer's own
# row, ellipsis icon first. Whether it worked is read off the menu's computed
# style rather than assumed.
MENU_SEL = ".menu"
TRIGGER_SELS = ("i.ellipsis", ".dropdown")
BUNDLE_SEL = "[data-tid='nub-bundle']"
SIGNER_SEL = "[data-tid^='nub-signerPk-']"
RESEND_SEL = "[data-tid='nub-sendText']"

# A bundle row worth opening: one that is out with somebody. A Draft was never
# delivered and a Cancelled/Declined/Expired one has nothing to re-send.
LIVE_ROW = re.compile(r"^(Sent|Started|Pending|New|Ready)\d")
# A row that is FINISHED. Looked for separately so a search that matched only
# these can say "they have already signed" instead of "nothing found": on
# 2026-11-24 all eleven people a chase planned for read
# `Complete11/23/26 <name>`, and the refusal called it "no live Blue Ink
# packet", which reads as a lost packet rather than a signed one.
DONE_ROW = re.compile(r"^(Completed|Complete|Signed)\d")

# A SIGNER'S LINE: `Employee:Nina Vale Sentnvargas@example.net`. The
# status and the address run together with NO separator, so the status has to
# be read as the prefix of what otherwise looks like the address -- every
# character of "Sent" is legal in a local part, and an address regex on its own
# happily returns `Sentnv@example.com`.
#
# Longest first in the alternation: "Complete" before "Completed" would match
# the short one and leave the "d" on the front of the address.
_PAIR_RE = re.compile(
    r"(Draft|Sent|Started|Pending|New|Ready|Completed|Complete|Signed|"
    r"Cancelled|Canceled|Declined|Expired|Failed|Voided)"
    r"\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
# The address ALONE, for the line whose status did not render. Both refuse to
# send, but one says "could not read the packet's state" and the other would
# say "not a signer on this bundle" about the right person -- and that second
# line is what somebody reads when deciding whether the chase is broken.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Already signed. A signer in this state is never resent to.
DONE = {"completed", "complete", "signed"}

SETTLE_TRIES = 20
DETAIL_MS = 6000


def _settle(page) -> str:
    """Wait for the three columns to finish fetching. Returns the body text.

    A column still loading renders "Loading envelopes..." and matches no row
    pattern at all, so reading through it finds nobody and this would report
    "no packet" about a packet that is right there.
    """
    body = ""
    for _ in range(SETTLE_TRIES):
        body = " ".join((page.inner_text("body") or "").split())
        if "Loading envelopes" not in body:
            return body
        page.wait_for_timeout(1000)
    return body


def close_detail(page) -> None:
    """Shut the detail modal so the list underneath is clickable again."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)
    except Exception:                                   # noqa: BLE001
        pass


def signers(page) -> List[Dict]:
    """Every signer on the OPEN bundle: pk, email, status, resend available.

    Read off the detail modal, so an empty list means the modal is not open
    (or the layout moved) -- never "this bundle has no signers".
    """
    raw = page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel[0])).map(e => ({
             pk: e.getAttribute('data-tid') || '',
             text: (e.innerText || '').replace(/\\s+/g, ' ').trim(),
             resend: !!e.querySelector(sel[1]),
           }))""",
        [SIGNER_SEL, RESEND_SEL])
    out = []
    for s in raw or []:
        text = s.get("text") or ""
        pair = _PAIR_RE.search(text)
        if pair:
            status, email = pair.group(1).lower(), pair.group(2)
        else:
            lone = _EMAIL_RE.search(text)
            status, email = "", (lone.group(0) if lone else "")
        out.append({"pk": s.get("pk") or "",
                    "status": status,
                    "email": email.strip().lower(),
                    "text": text,
                    "resend": bool(s.get("resend"))})
    return out


def _menu_open(page, pk: str) -> bool:
    """Is this signer's action dropdown showing?"""
    try:
        return page.evaluate(
            """(a) => {
                 const m = document.querySelector("[data-tid='" + a[0] + "'] " + a[1]);
                 return !!m && getComputedStyle(m).display !== 'none';
               }""", [pk, MENU_SEL])
    except Exception:                                   # noqa: BLE001
        return False


def open_signer_menu(page, pk: str, log=print) -> bool:
    """Open that signer's ... dropdown, so Resend is a real, clickable thing."""
    if _menu_open(page, pk):
        return True
    for which in TRIGGER_SELS:
        el = page.query_selector("[data-tid='%s'] %s" % (pk, which))
        if el is None:
            continue
        try:
            el.click(timeout=8000)
        except Exception as exc:                        # noqa: BLE001
            log("    the signer's menu would not open (%s on %s)"
                % (type(exc).__name__, which))
            continue
        page.wait_for_timeout(700)
        if _menu_open(page, pk):
            return True
    return False


def _receipts(page, email: str) -> int:
    """How many times the Event Log says a link went to this address.

    The count, not a boolean: the first send is already in the log, so the
    only honest proof a resend happened is that the count went UP.
    """
    try:
        text = page.inner_text(DETAIL_SEL) or ""
    except Exception:                                   # noqa: BLE001
        return 0
    text = " ".join(text.split())
    want = re.escape(str(email or "").strip().lower())
    if not want:
        return 0
    return len(re.findall(r"sent via email to [^@]*?at\s+" + want, text, re.I))


def open_bundle(page, term: str, log=print):
    """Search for `term` and open the newest LIVE bundle it matches.

    Returns (label, why): the row's label when one opened, else None with a
    word for why -- "signed" when every row the search matched is finished,
    "none" when there is nothing at all, "dead" for drafts and cancellations
    only. A caller that cannot tell those apart reports a signed packet as a
    missing one.
    """
    U.open_dashboard(page)
    U._search(page, term)
    _settle(page)
    rows = [" ".join((r.inner_text() or "").split())
            for r in page.query_selector_all(BUNDLE_SEL)]
    live = [i for i, t in enumerate(rows) if LIVE_ROW.match(t)]
    if not live:
        if any(DONE_ROW.match(t) for t in rows):
            return None, "signed"
        return None, ("dead" if rows else "none")
    el = page.query_selector_all(BUNDLE_SEL)[live[0]]
    label = rows[live[0]]
    el.click()
    page.wait_for_timeout(DETAIL_MS)
    if page.query_selector(DETAIL_SEL):
        return label, "open"
    # Clicked and nothing opened: say so rather than reading an empty modal
    # as a bundle with no signers.
    log("    the bundle row opened nothing (%s)" % label[:50])
    close_detail(page)
    return None, "stuck"


# What an inspection concluded. Only WOULD_SEND is ever acted on.
WOULD_SEND = "would_send"
SIGNED = "signed"
NO_PACKET = "no_packet"
NOT_A_SIGNER = "not_a_signer"
UNREADABLE = "unreadable"
NO_CONTROL = "no_control"
NO_ADDRESS = "no_address"

_SAYS = {
    SIGNED: "already signed — no reminder",
    NO_PACKET: "no live Blue Ink packet to re-send",
    NOT_A_SIGNER: "not a signer on that bundle — not re-sent",
    UNREADABLE: "could not read the packet's state — not re-sent",
    NO_CONTROL: "no Resend on this signer — not re-sent",
    NO_ADDRESS: "no address to re-send to",
}


def inspect(page, term: str, email: str, log=print):
    """Everything read BEFORE any click: the verdict, and the signer if any.

    Split out so a dry run reports the SAME verdict a real send would act on.
    It did not, and the difference mattered: on 2026-11-24 the dry run said
    "would remind" for eleven people who had all signed, because the dry path
    answered from the plan rather than from the screen
    ([[feedback_dont_explain_away_a_zero]] in reverse -- a reassuring answer
    nothing had checked).

    Leaves the detail modal OPEN on WOULD_SEND, because that is the page the
    click needs; closes it on every other verdict.
    """
    who = str(email or "").strip().lower()
    if not who:
        return NO_ADDRESS, None, ""
    label, why = open_bundle(page, term, log=log)
    if label is None:
        return (SIGNED if why == "signed" else NO_PACKET), None, ""
    found = [s for s in signers(page) if s["email"] == who]
    if not found:
        # The address on the sheet is not always the address the packet went
        # to (`recent_ui` says the same thing about searching). Refuse rather
        # than resending to whoever else is on the bundle.
        close_detail(page)
        return NOT_A_SIGNER, None, label
    s = found[0]
    if s["status"] in DONE:
        close_detail(page)
        return SIGNED, s, label
    if not s["status"]:
        close_detail(page)
        return UNREADABLE, s, label
    if not s["resend"]:
        close_detail(page)
        return NO_CONTROL, s, label
    return WOULD_SEND, s, label


def says(verdict: str) -> str:
    """The sentence for a verdict, so the chase and a probe word it the same."""
    return _SAYS.get(verdict, verdict)


def resend(page, term: str, email: str, *, dry_run: bool = True,
           log=print) -> bool:
    """Re-send the invitation for `email` on the bundle that `term` finds.

    True only when the Event Log gained a new receipt for that address. A dry
    run reads everything, clicks nothing, and answers False -- it has not
    sent, and a caller that writes a ledger row on True must not write one.
    Ask `inspect` when you need to know whether it WOULD have.
    """
    who = str(email or "").strip().lower()
    verdict, s, label = inspect(page, term, email, log=log)
    if verdict != WOULD_SEND:
        log("    %s: %s" % (term, says(verdict)))
        return False
    before = _receipts(page, who)
    if dry_run:
        log("    %s: would re-send (%s, %s receipt(s) logged so far)"
            % (term, s["status"], before))
        close_detail(page)
        return False
    if not open_signer_menu(page, s["pk"], log=log):
        log("    %s: could not open the signer's menu — not re-sent" % term)
        close_detail(page)
        return False
    # Scoped to THIS signer's block. A bare RESEND_SEL would take whichever
    # signer the app rendered first, which on a multi-signer bundle is the
    # wrong person.
    btn = page.query_selector("[data-tid='%s'] %s" % (s["pk"], RESEND_SEL))
    if btn is None:
        log("    %s: the Resend control went away — not re-sent" % term)
        close_detail(page)
        return False
    try:
        btn.click(timeout=15000)
    except Exception as exc:                            # noqa: BLE001
        # NEVER RAISES PAST HERE. A chase runs through a handful of people in
        # one browser, and a click that timed out on one must not take the
        # rest of them with it.
        log("    %s: the Resend click did not land (%s) — not re-sent"
            % (term, type(exc).__name__))
        close_detail(page)
        return False
    # WAIT FOR THE RECEIPT, not for a fixed moment. The click is a request;
    # the Event Log line is the app saying it happened.
    for _ in range(15):
        page.wait_for_timeout(1000)
        if _receipts(page, who) > before:
            log("    %s: re-sent — the event log says the link went to %s"
                % (term, who))
            close_detail(page)
            return True
    log("    %s: clicked Resend and the event log never said it went — "
        "treating it as NOT sent" % term)
    close_detail(page)
    return False


class Session:
    """One signed-in browser for a whole chase run.

    Opening it is the slow part (`recent_ui` prices the same thing), and a
    chase wakes with a handful of people at most, so they share one.

    Used as a context manager so the browser closes on any exit path:
    a chase that leaves a headless Chromium behind on an office machine is a
    process the owner never sees and never quits.
    """

    def __init__(self, *, headless: bool = True):
        self._headless = headless
        self._p = None
        self._closeable = None
        self.page = None

    def __enter__(self):
        from patchright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self._closeable, ctx = S.open_context(self._p, headless=self._headless)
        self.page = ctx.pages[0] if getattr(ctx, "pages", None) else ctx.new_page()
        return self

    def __exit__(self, *exc):
        for shut in (getattr(self._closeable, "close", None),
                     getattr(self._p, "stop", None)):
            try:
                if shut:
                    shut()
            except Exception:                           # noqa: BLE001
                pass
        return False

    def resend(self, term: str, email: str, *, dry_run: bool = True,
               log=print) -> bool:
        return resend(self.page, term, email, dry_run=dry_run, log=log)

    def inspect(self, term: str, email: str, log=print):
        return inspect(self.page, term, email, log=log)
