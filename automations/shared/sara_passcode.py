"""SaraPlus's "new location or browser" screen: ask for the code, type it in.

ONE COPY OF THE PAGE STEPS. They were written for rc_contact_sync, which reads
its codes straight out of the reporting inbox, and they are the hard part:
the Email "radio" is a Telerik toggle, Get Code with it unticked sends
nothing, the code box only appears on the second screen, and SaraPlus has
issued two codes a second apart. All of that was learnt on the live page
(2026-09-03 .. 10-10) and is kept here, word for word.

WHY IT MOVED HERE (2026-10-29). The office Macs need the same steps --
Eveliz, Luke, Rashad and Tre are asked for a code on every fresh login -- and
what ships to those Macs cannot pull in rc_contact_sync, its inbox reader or
the sales board. So the page steps live in shared/ with nothing heavier than
the standard library, and each caller says where its code comes from:
rc_contact_sync from its inbox, an office Mac from the relay
(icd_alerts.sara_code).

Python 3.9-safe (the office Macs run Apple's 3.9).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable

NAV_TIMEOUT_MS = 60_000
# Long enough for a double-issued PAIR of codes to both land before anybody
# reads the inbox (see verify_browser).
SETTLE_MS = 6000


class PasscodeError(RuntimeError):
    """The code screen did something these steps do not know how to answer."""


def _on_passcode_page(page) -> bool:
    """Still sitting on SaraPlus's own verification page (Security/
    VerifyPasscode.aspx). The URL is the honest signal that the challenge has
    not been cleared."""
    try:
        url = (page.url or "").lower()
    except Exception:                                      # noqa: BLE001
        return False
    return "passcode" in url or "verifycode" in url or "/security/" in url


def _settle(page, timeout_ms: int = 30_000) -> None:
    """Wait until the page has LEFT the passcode URL or has something on it.

    networkidle after typing the code is not proof the next page is there:
    2026-10-10 on Lucy 2 the run read a page with no HTML at all (still the
    VerifyPasscode url, mid-reload), took 'still on the passcode page' at
    face value, went round for a fresh code on that blank page, found no
    Email button and died. A blank page is not an answer -- wait for one."""
    deadline = dt.datetime.now() + dt.timedelta(milliseconds=timeout_ms)
    while dt.datetime.now() < deadline:
        if not _on_passcode_page(page):
            return
        try:
            text = (page.evaluate(
                "() => (document.body && document.body.innerText) || ''") or "")
        except Exception:                                  # noqa: BLE001
            text = ""                                      # navigating
        if text.strip():
            return
        page.wait_for_timeout(1000)


def _needs_code(page) -> bool:
    """Is this login being asked to prove the browser? Judged on the PAGE, not
    on finding a text box -- the first screen is a destination picker that has
    no code box on it at all, and the box only appears on the next one."""
    try:
        url = (page.url or "").lower()
        body = (page.evaluate("() => (document.body.innerText || '')") or "").lower()
    except Exception:                                      # noqa: BLE001
        return False
    if "passcode" in url or "verifycode" in url:
        return True
    return any(n in body for n in
               ("confirmation code", "verification code", "security code",
                "new location or browser", "enter the code"))


def _code_field(page):
    """The input to TYPE the code into, or None if this page has no such box.

    TEXT-LIKE INPUTS ONLY. It used to accept any non-password input whose id
    matched /code/, and on the picker screen that is `btnGetCodeEmail` -- the
    Get Code BUTTON. The code was then 'typed' into a submit button, which
    does exactly nothing, and the run failed one page later claiming the code
    had expired (2026-09-03).

    Matched by id/name/placeholder first, then by 'the one visible text box on
    a page that is asking for a code'."""
    return page.evaluate(
        """() => {
             const typable = e => ['text', 'tel', 'number', 'search', ''].includes(e.type);
             const els = [...document.querySelectorAll('input')].filter(typable);
             for (const e of els) {
               if (e.readOnly || e.disabled) continue;
               const hay = [e.id, e.name, e.placeholder,
                            e.getAttribute('aria-label') || ''].join(' ').toLowerCase();
               if (/code|otp|verif|token|pin/.test(hay)) return e.id || e.name || '';
             }
             const body = (document.body.innerText || '').toLowerCase();
             if (!/verification|security code|confirmation code|one-time|enter the code/.test(body))
               return null;
             const visible = els.filter(e => !e.readOnly && !e.disabled &&
                                             e.offsetParent !== null);
             return visible.length === 1 ? (visible[0].id || visible[0].name || '') : null;
           }""")


def code_page_text(page, limit: int = 400) -> str:
    """What the code step actually SAYS. Printed on every code-step run and
    captured by --probe, because the first live attempt failed with 'no code
    arrived' and there was no way to tell a page that had already sent one
    from a page still waiting to be asked."""
    try:
        txt = page.evaluate("() => (document.body.innerText || '')")
    except Exception:                                      # noqa: BLE001
        return ""
    return re.sub(r"\s*\n\s*", " | ", (txt or "").strip())[:limit]


def code_page_controls(page) -> dict:
    """Every control on the destination picker, so a failure says what was
    actually on screen instead of 'no code arrived'."""
    return page.evaluate(
        """() => {
             const out = {radios: [], selects: [], buttons: []};
             document.querySelectorAll('input[type=radio],input[type=checkbox]').forEach(e => {
               const lab = (e.labels && e.labels[0] && e.labels[0].innerText || '').trim();
               out.radios.push({id: e.id, name: e.name, value: e.value,
                                label: lab || (e.parentElement || {}).innerText || ''});
             });
             document.querySelectorAll('select').forEach(e => {
               out.selects.push({id: e.id, name: e.name,
                 options: [...e.options].map(o => ({value: o.value, text: (o.text || '').trim()}))});
             });
             document.querySelectorAll('input[type=submit],input[type=button],button').forEach(e => {
               const t = (e.value || e.innerText || '').trim();
               if (t) out.buttons.push(t.slice(0, 40));
             });
             // The picker turned out to be none of the above (2026-09-03:
             // radios [], selects [], one 'Get Code' button), so links,
             // click handlers and the raw markup around the choice are dumped
             // too -- a control we cannot name is one we cannot click.
             out.links = [...document.querySelectorAll('a')]
               .map(a => ({text: (a.innerText || '').trim().slice(0, 30),
                           id: a.id, href: (a.getAttribute('href') || '').slice(0, 60),
                           onclick: (a.getAttribute('onclick') || '').slice(0, 80)}))
               .filter(a => a.text || a.onclick);
             out.clickable = [...document.querySelectorAll('[onclick]')]
               .map(e => ({tag: e.tagName, id: e.id,
                           text: (e.innerText || '').trim().slice(0, 30),
                           onclick: (e.getAttribute('onclick') || '').slice(0, 80)}));
             out.textInputs = [...document.querySelectorAll('input')]
               .filter(e => e.type !== 'hidden')
               .map(e => ({type: e.type, id: e.id, name: e.name,
                           value: (e.value || '').slice(0, 30)}));
             const hit = [...document.querySelectorAll('table,form,div')]
               .filter(e => /Email:/.test(e.innerText || '') &&
                            (e.innerHTML || '').length < 4000)
               .pop();
             out.html = hit ? hit.innerHTML.replace(/[ \\t\\n\\r]+/g, ' ').slice(0, 1500) : '';
             return out;
           }""")


def _choose_email_destination(page, log=print) -> bool:
    """Tick the EMAIL radio, then pick the address. Both, in that order.

    THE RADIO IS NOT AN <input type=radio>. It is a Telerik RadButton toggle
    -- a <span id=...rbEmailRadio> whose real state lives in a hidden
    ClientState blob ('"checked":false', '"autoPostBack":true'), exactly the
    shape as the RadDatePicker the date range needs. Nothing in a normal
    control dump sees it, which is why three attempts in a row reported "no
    email destination" while looking straight at one.

    The address beside it is a RadComboBox (id ...rcbEmailOptions_Input,
    readonly, pre-filled 'Carl...@gmail.com'). Pre-filled is not chosen: the
    combo displays the address before anything is selected.

    Get Code with the radio unticked sends NOTHING and says nothing -- it
    reads as a broken mail filter. Read off the live page 2026-09-03; matched
    on 'EmailRadio' / 'Email' inside the ids so a rename still resolves.

    It has to be email: the other destination is a mobile number an
    unattended run cannot read, and which would text a person at 4am."""
    radio = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll('span,div,label')];
             const e = els.find(x => /emailradio/i.test(x.id || ''))
                    || els.find(x => /rbToggle|RadButton/.test(x.className || '') &&
                                     /^email:?$/i.test((x.innerText || '').trim()));
             if (!e) return '';
             e.click();
             return e.id || 'email-toggle';
           }""")
    if radio:
        log("  ticked the Email radio (%s)" % radio)
        # autoPostBack:true — the page reloads itself before Get Code means
        # anything, and every element found before this is now stale.
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:                                  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)

    combo = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll('input')].filter(e => e.type !== 'hidden');
             const e = els.find(x => /email/i.test(x.id || '') || /email/i.test(x.name || ''))
                    || els.find(x => /@/.test(x.value || ''));
             return e ? {id: e.id, value: e.value || ''} : null;
           }""")
    if not combo:
        return bool(radio)
    log("  email destination on file: %s" % (combo["value"] or "(blank)"))
    try:
        page.click("#%s" % combo["id"])
        page.wait_for_timeout(900)
    except Exception:                                      # noqa: BLE001
        pass
    picked = page.evaluate(
        """() => {
             const items = document.querySelectorAll('.rcbList li, [class*="rcbItem"]');
             for (const el of items) {
               const t = (el.textContent || '').trim();
               if (/@/.test(t)) { el.click(); return t; }
             }
             return '';
           }""")
    if picked:
        log("  address chosen from the list: %s" % picked)
        page.wait_for_timeout(900)
        return True
    if "@" in (combo["value"] or ""):
        log("  no dropdown list appeared — using the address already in the box")
        return True
    return bool(radio)


def _request_code(page, log=print, error=None) -> bool:
    """Choose EMAIL, then press Get Code.

    The screen is a destination picker -- 'It appears that this is a new
    location or browser for you to login from ... select a location to
    receive a confirmation code' -- offering a mobile number and an email
    combo. Pressing Get Code without choosing sends nothing at all, silently:
    that is what the first two attempts did, and it read as a broken mail
    filter rather than an unpicked control."""
    if not _choose_email_destination(page, log=log):
        raise (error or PasscodeError)(
            "SaraPlus wants a confirmation code for this browser but no EMAIL "
            "destination could be found on the picker -- and the only other "
            "option is the mobile number, which an unattended run cannot read "
            "and which would text a person at 4am. Nothing was requested. "
            "Controls on the page: %s" % (code_page_controls(page),))
    clicked = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll(
               'input[type=submit],input[type=button],button,a')];
             // The EMAIL button by id first (MainContent_btnGetCodeEmail on
             // the live page): the screen carries one Get Code per
             // destination, and matching on the visible text alone could
             // press the phone's.
             const want = /get code|send.*code|email.*code|request.*code|resend|send me/i;
             const b = els.find(e => /getcodeemail/i.test(e.id || e.name || ''))
                    || els.find(e => {
                         const t = (e.value || e.innerText || '').trim();
                         return t && t.length < 40 && want.test(t);
                       });
             if (!b) return '';
             b.click();
             return ((b.value || b.innerText || '').trim() + ' [' + (b.id || '?') + ']');
           }""")
    if clicked:
        log("  asked SaraPlus to send the code (%r)" % clicked)
        page.wait_for_timeout(2500)
        return True
    log("  no 'Get Code' button found — assuming the code was already sent")
    return False


def _submit_code(page, field: str, code: str) -> None:
    """Type the code and press whatever continues. Typed character by
    character like the password: this is the same old ASP.NET form, and it
    drops a value that arrives in one paste-like event."""
    sel = ("#%s" % field) if field else "input[type=text]:visible"
    box = page.locator(sel).first
    box.click()
    if hasattr(box, "press_sequentially"):
        box.press_sequentially(code, delay=60)
    else:
        box.type(code, delay=60)
    clicked = page.evaluate(
        """() => {
             const btns = [...document.querySelectorAll(
               'input[type=submit],input[type=button],button,a')];
             const want = /verify|submit|continue|confirm|log ?in|next/i;
             const b = btns.find(e => want.test((e.value || e.innerText || '').trim()));
             if (b) { b.click(); return true; }
             return false;
           }""")
    if not clicked:
        page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(1000)
    _settle(page)



def verify_browser(page, get_code: Callable[[dt.datetime], str], *,
                   attempts: int = 3, settle_ms: int = SETTLE_MS,
                   error=None, log=print) -> None:
    """Clear the code screen, RETRYING with a fresh code each time.

    The same loop as rc_contact_sync.sara._verify_browser -- read its
    docstring for why one pass is not enough -- with the one difference that
    matters: `get_code(since)` is the caller's, so the code can come from an
    inbox, the relay, or anywhere else. It must return a code that arrived
    AFTER `since`, or raise.
    """
    err = error or PasscodeError
    for attempt in range(1, attempts + 1):
        # Stamped BEFORE the request and a little early: this clock and
        # Gmail's are not identical, and a code thrown away for being a
        # second too old looks exactly like a code that never arrived.
        since = dt.datetime.now().astimezone() - dt.timedelta(seconds=30)
        _settle(page)
        if not _on_passcode_page(page) and attempt > 1:
            log("  browser verified (attempt %d, page caught up)" % (attempt - 1))
            return
        if not _request_code(page, log=log, error=err):
            log("  nothing to press for a code on attempt %d" % attempt)
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:                                  # noqa: BLE001
            pass
        page.wait_for_timeout(settle_ms)
        field_id = _code_field(page)
        if field_id is None:
            raise err(
                "SaraPlus asked to verify this browser and a code was "
                "requested, but no box to type it into appeared. Page says: %s"
                % code_page_text(page))
        code = get_code(since)
        _submit_code(page, field_id, code)
        # Judged on the URL, not the words: the Hub carries enough of the
        # same vocabulary to read as "still being asked".
        if not _on_passcode_page(page):
            log("  browser verified (attempt %d)" % attempt)
            return
        log("  still on the passcode page after attempt %d -- asking for a "
            "fresh code" % attempt)
    raise err(
        "SaraPlus would not accept a verification code after %d attempts, each "
        "one newer than its own request -- the challenge itself is not "
        "clearing. Page says: %s" % (attempts, code_page_text(page)))
