"""Lucy clicks through Gmail for the owner: our forwarding address, then the filter.

WHY (Eve 2026-11-17: "es imposible retener a los dueños por unos minutos,
apenas si contestan un slack"). 7 of 18 offices never finished the SaraPlus
code forward; Kash pressed OK three times (11/10, 11/14, 11/17) and Gmail's
confirmation never reached us. Tried end to end on a real Gmail the same day
(Eve's test box): after "Next" in "Add a forwarding address" GOOGLE SHOWS A
NUMBER AND WANTS IT TAPPED ON THE OWNER'S PHONE. Our steps never said so, so an
owner saw a strange number and stopped. Only after the tap does Gmail mail the
confirmation to the reporting inbox.

So the owner does two things, and Lucy does every click around them:
  1. signs in to Gmail in Lucy's window (the session stays in PROFILE),
  2. taps on their phone the number Lucy shows them.
Lucy adds the address, Lucy 1 confirms Gmail's mail (code_answer), and Lucy
makes the filter and reads it back from Gmail's filter list -- that read-back
is the proof. Anything unexpected returns a word and the caller falls back to
the hand-built steps, so this is never worse than before.

WHAT GMAIL LOOKS LIKE (read off real pages 2026-11-17, Spanish accounts):
  * NOT BY TEXT. Gmail answers in the account's language whatever ?hl= says,
    and button classes are scrambled. Everything here goes by structure: the
    forwarding radios (input[name=sx_em]), the dialog's email box, the filter
    panel (.ZZ), the address our own text names.
  * #settings/fwdandpop LOADED DIRECTLY IS A LIGHT PAGE, for good: a plain
    text box, no add button, and typing a new address there answers "invalid
    forwarding address". The real page (with the button) only comes when Gmail
    is already open and moves there itself. So Lucy opens the inbox first and
    then changes location.hash (_go), and never types into that box.
  * The filter box is the other way round: changing the hash from inside
    Gmail did not always open it, a fresh load (?lucy=<n>) did. _make_filter
    tries the hash, then a fresh load.
  * In the filter's second step the address list is only filled once clicked;
    the right list is the one that offers OUR address.

NEVER "FORWARD A COPY". That radio forwards the whole inbox. Nothing here
touches it, and typing into the light page's box (which flips it on) is
exactly what this never does.

Patchright, like every Lucy browser. MAC AND WINDOWS (tried on Windows).
"""
from __future__ import annotations

import platform
import re
import time
from typing import Optional
from urllib.parse import quote

from automations.icd_alerts import config as C

PROFILE = C.APP_DIR / "gmail-browser"
REPORTING_INBOX = "alphaletereporting@gmail.com"
SARAPLUS_SENDER = "security.info@saraplus.com"

SIGNIN_MAX_S = 600        # the owner types their password, maybe a 2-step code
PAGE_MAX_S = 60           # Gmail's real settings page, after the light one
PHONE_MAX_S = 300         # the tap on the phone
NUMBER_GRACE_S = 12       # Google's number shows a few seconds after "phone"

# What each call answers. The caller only needs: worked, or show the hand steps.
ADDED = "address added"          # Gmail is mailing the confirmation now
ALREADY = "address already there"
MADE = "filter made"             # read back from Gmail's filter list
NOT_ACCEPTED = "address not accepted yet"
NO_SIGNIN = "nobody signed in"
WRONG_ACCOUNT = "signed in to another account"
NO_BROWSER = "no browser"
STUCK = "gmail looked different"
NO_TAP = "owner did not tap the phone"     # asked, and nothing came of it

SIGN_IN = ("Lucy will set this up for you. You only do 2 things.\n\n"
           "1. A Gmail window opens. Sign in to %s.\n"
           "2. If your phone shows a number, tap the same number.\n\n"
           "Lucy does everything else. Click OK to open Gmail.")
# Megan's red bar (shared/browser_banner), up from the moment the owner is
# signed in until Lucy closes the window, in the Google window too. Without
# it the obvious thing to do with a Gmail screen that moves by itself is to
# help it along (Eve 2026-11-17). Pointer events off: it never blocks a click.
BANNER_TITLE = "DON'T TOUCH THIS WINDOW - LUCY IS WORKING"
BANNER_DETAIL = ("Only if your phone shows a number: tap the same number on your phone. "
                 "Lucy clicks everything here and closes this window by herself.")
# Between the address and the filter Lucy 1 confirms Gmail's mail (up to a few
# minutes). ONE window the whole way (Eve 2026-11-17: a window that closes and
# another that opens later is one more thing to wonder about).
BANNER_WAITING = ("Lucy is waiting for Gmail - up to 3 minutes. Leave this window open. "
                  "Only if your phone shows a number: tap the same number.")

PHONE = ("Look at your phone now.\n\n"
         "Google is asking if it's you. Tap %s.\n\n"
         "If Google asks for your password in the Gmail window, type it there.")
PHONE_NO_NUMBER = ("Look at your phone now.\n\n"
                   "Google is asking if it's you. Tap Yes.\n\n"
                   "If Google asks for your password in the Gmail window, type it there.")

_VIS = "e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"

# The forwarding section: the radios' highest ancestor that does not reach the
# POP section (bx_pe). Answers what it holds, and tags the add button.
_FORWARD_STATE = """(inbox) => {
  const vis = %s;
  const radio = document.querySelector('input[name=sx_em]');
  if (!radio) return 'loading';
  let sec = radio;
  while (sec.parentElement && !sec.parentElement.querySelector('input[name=bx_pe]')) sec = sec.parentElement;
  const text = (sec.innerText || '').toLowerCase();
  if (text.includes(inbox)) return 'listed';
  const btn = [...sec.querySelectorAll('button, [role=button], input[type=button]')].find(vis);
  if (!btn) return 'loading';
  document.querySelectorAll('[data-lucy]').forEach(e => e.removeAttribute('data-lucy'));
  btn.setAttribute('data-lucy', 'add');
  return 'ready';
}""" % _VIS

# The open dialog with an email box: tags the box and its LAST button (Next).
_ADD_DIALOG = """() => {
  const vis = %s;
  for (const d of document.querySelectorAll('[role=dialog], [role=alertdialog]')) {
    if (!vis(d)) continue;
    const box = [...d.querySelectorAll('input[type=email], input[type=text]')].find(vis);
    const btns = [...d.querySelectorAll('button, [role=button]')].filter(vis);
    if (!box || btns.length < 2) continue;
    box.setAttribute('data-lucy', 'box');
    btns[btns.length - 1].setAttribute('data-lucy', 'next');
    return true;
  }
  return false;
}""" % _VIS

# A dialog with no box (Gmail's "confirmation sent" notice): tags its last button.
_NOTICE = """() => {
  const vis = %s;
  for (const d of document.querySelectorAll('[role=dialog], [role=alertdialog]')) {
    if (!vis(d) || [...d.querySelectorAll('input')].some(vis)) continue;
    const btns = [...d.querySelectorAll('button, [role=button]')].filter(vis);
    if (!btns.length) continue;
    btns[btns.length - 1].setAttribute('data-lucy', 'notice');
    return (d.innerText || '').slice(0, 200);
  }
  return '';
}""" % _VIS

# Google's "forward to ...?" window: tags its one submit (Proceed).
_ONE_SUBMIT = """() => {
  const vis = %s;
  const subs = [...document.querySelectorAll('input[type=submit], button[type=submit]')].filter(vis);
  if (subs.length !== 1) return false;
  subs[0].setAttribute('data-lucy', 'proceed');
  return true;
}""" % _VIS

# The filter panel: tags its last button ("Create filter", both steps) and says
# which step it is on (the second has lists).
_PANEL = """(sender) => {
  const vis = %s;
  // TWO copies of the panel are on the page; only the LAST one answers a
  // press (tried by hand and by Lucy, 11/17).
  const p = [...document.querySelectorAll('.ZZ')].filter(vis).pop();
  if (!p) return 'none';
  const btns = [...p.querySelectorAll('button')].filter(vis);
  if (!btns.length) return 'none';
  document.querySelectorAll('[data-lucy]').forEach(e => e.removeAttribute('data-lucy'));
  btns[btns.length - 1].setAttribute('data-lucy', 'create');
  // Step 1 shows the From box (SaraPlus already in it). Its size menus are
  // listboxes too, so lists alone don't tell the steps apart (11/17).
  const from = [...p.querySelectorAll('input[type=text]')].filter(vis)
    .some(i => (i.value || '').toLowerCase() === sender);
  if (from) return 'step1';
  const lists = [...p.querySelectorAll('[role=listbox]')].filter(vis);
  lists.forEach((l, i) => l.setAttribute('data-lucy-list', String(i)));
  return 'step2:' + lists.length;
}""" % _VIS

# After a list was clicked: tags OUR address among the open options.
_OUR_OPTION = """(inbox) => {
  const vis = %s;
  // The open menu's copy is the LAST one; the list itself shows it too.
  const o = [...document.querySelectorAll('[role=option]')].filter(vis)
    .filter(o => (o.innerText || '').trim().toLowerCase() === inbox).pop();
  if (!o) return false;
  o.setAttribute('data-lucy', 'option');
  return true;
}""" % _VIS

# The checkbox on the same line as list n: tags it, answers whether it is ticked.
_ITS_BOX = """(n) => {
  let c = document.querySelector('[data-lucy-list="' + n + '"]');
  for (let i = 0; i < 6 && c; i++) {
    c = c.parentElement;
    const cb = c && c.querySelector('input[type=checkbox]');
    if (cb) { cb.setAttribute('data-lucy', 'forward'); return cb.checked; }
  }
  return null;
}"""

# Gmail's filter list: one row naming SaraPlus AND our address.
_FILTER_LISTED = """([sender, inbox]) => [...document.querySelectorAll('tr')]
  .some(t => { const s = (t.innerText || '').toLowerCase(); return s.includes(sender) && s.includes(inbox); })"""


def gmail_url(address: str, screen: str) -> str:
    """Gmail on `screen`, in THAT account, reloaded (a fresh ?lucy= each time)."""
    return ("https://mail.google.com/mail/?authuser=%s&lucy=%d#%s"
            % (quote(address, safe="@"), int(time.time() * 1000) % 10 ** 9, screen))


def signin_url(address: str) -> str:
    return ("https://accounts.google.com/AccountChooser?service=mail&Email=%s&continue=%s"
            % (quote(address, safe="@"), quote("https://mail.google.com/mail/", safe="")))


def _launch(p):
    PROFILE.mkdir(parents=True, exist_ok=True)
    # No Chrome bubbles over Lucy's work (Eve's test, 11/17): no first-run or
    # default-browser asks, no "Make Chrome your own" after the Google sign-in.
    base = dict(user_data_dir=str(PROFILE), headless=False, no_viewport=False,
                args=["--disable-sync", "--window-size=1280,900", "--no-first-run",
                      "--no-default-browser-check",
                      "--disable-features=DiceWebSigninInterception,"
                      "ExplicitBrowserSigninUIOnDesktop,SigninInterceptBubbleV2"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base)
    except Exception:  # noqa: BLE001 -- no Google Chrome installed: patchright's own
        return p.chromium.launch_persistent_context(**base)


def _account_in(title: str) -> str:
    """Gmail's tab title names the account: 'Inbox (3) - a@b.com - Gmail'."""
    m = re.search(r"([\w.+'-]+@[\w-]+(?:\.[\w-]+)+)\s*-\s*Gmail\s*$", title or "")
    return m.group(1).lower() if m else ""


# The ONE thing the owner does in this window, said IN the window (Eve
# 2026-11-17, on the test: "pensé que Lucy se logueaba sola" -- the box that
# said so had been read and closed, or never seen). Blue, not red: here the
# owner SHOULD act. Repainted every pass, Google's sign-in moves page to page.
_SIGNIN_BAR = """(text) => {
  const ID = '__lucy_signin_bar';
  if (!document.body || document.getElementById(ID)) return;
  const bar = document.createElement('div');
  bar.id = ID;
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
    'background:#0b57d0;color:#fff;text-align:center;padding:16px 18px;' +
    'font:700 clamp(22px,3vw,36px)/1.2 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;' +
    'pointer-events:none;box-shadow:0 2px 6px rgba(0,0,0,.35)';
  bar.textContent = text;
  document.body.appendChild(bar);
}"""
SIGNIN_TEXT = "SIGN IN HERE to %s - that's all. Lucy does the rest."


def _wait_signed_in(pg, address: str, clock=time.time, sleep=time.sleep,
                    max_s: int = SIGNIN_MAX_S, bar: bool = False) -> str:
    """Until Gmail shows THAT account. '' when it does, else a reason word.
    bar=True keeps the blue "sign in here" bar up while it waits."""
    end = clock() + max_s
    seen = ""
    while clock() < end:
        try:
            seen = _account_in(pg.title())
        except Exception:  # noqa: BLE001 -- mid-navigation
            seen = ""
        if seen == address.lower():
            return ""
        if bar:
            try:
                pg.evaluate(_SIGNIN_BAR, SIGNIN_TEXT % address)
            except Exception:  # noqa: BLE001 -- mid-navigation: next pass
                pass
        sleep(2)
    return WRONG_ACCOUNT if seen else NO_SIGNIN


def _wait_for(pg, js: str, arg=None, want=lambda v: bool(v), max_s: int = PAGE_MAX_S,
              sleep=time.sleep, clock=time.time):
    end = clock() + max_s
    value = None
    while clock() < end:
        try:
            value = pg.evaluate(js, arg) if arg is not None else pg.evaluate(js)
        except Exception:  # noqa: BLE001 -- the page is still loading
            value = None
        if want(value):
            return value
        sleep(1)
    return value


def _phone_number(text: str) -> str:
    """The number Google asks the owner to tap: a line that is only 1-3 digits."""
    for line in (text or "").splitlines():
        if re.fullmatch(r"\s*\d{1,3}\s*", line):
            return line.strip()
    return ""


_banner_detail = {"text": BANNER_DETAIL}


def _banner(pg, detail: str = "") -> None:
    """Megan's red bar on this page. Never raises: no bar never stops Lucy.
    A new `detail` replaces the bar's words (it is redrawn, not edited)."""
    try:
        from automations.shared import browser_banner as BB
        if detail and detail != _banner_detail["text"]:
            _banner_detail["text"] = detail
            pg.evaluate("() => { const b = document.getElementById('__alphalete_alerts_banner');"
                        " if (b) b.remove(); }")
        pg.evaluate(BB._SCRIPT.strip(), {"title": BANNER_TITLE, "detail": _banner_detail["text"]})
    except Exception:  # noqa: BLE001
        pass


def _show(ask, body: str) -> None:
    """Tell the owner without stopping the clicks (a box on its own thread)."""
    import threading
    threading.Thread(target=lambda: _quiet(ask.message, body), daemon=True).start()


def _quiet(fn, *a):
    try:
        fn(*a)
    except Exception:  # noqa: BLE001
        pass


def _go(pg, address: str, screen: str) -> None:
    """Move INSIDE an open Gmail to `screen` (see the top: a direct load of the
    forwarding page never shows the add button)."""
    if _account_in(pg.title()) != address.lower():
        pg.goto(gmail_url(address, "inbox"), wait_until="domcontentloaded", timeout=60000)
        _wait_signed_in(pg, address, max_s=60)
        _banner(pg)
    pg.evaluate("h => { location.hash = h; }", "#inbox")
    time.sleep(2)
    pg.evaluate("h => { location.hash = h; }", "#" + screen)
    _banner(pg)


def _reload(pg, address: str) -> None:
    """A fresh Gmail, in that account, with the red bar."""
    pg.goto(gmail_url(address, "inbox"), wait_until="domcontentloaded", timeout=60000)
    _wait_signed_in(pg, address, max_s=60)
    _banner(pg, BANNER_DETAIL)


def _add_address(ctx, pg, address: str, ask, say=print) -> str:
    """Our address into Gmail's forwarding list. Answers ADDED/ALREADY or a reason."""
    _go(pg, address, "settings/fwdandpop")
    state = _wait_for(pg, _FORWARD_STATE, REPORTING_INBOX,
                      want=lambda v: v in ("listed", "ready"))
    if state == "listed":
        return ALREADY
    if state != "ready":
        say("      gmail: the add button never showed (%s)" % state)
        return STUCK
    pg.click('[data-lucy="add"]', timeout=10000)
    if not _wait_for(pg, _ADD_DIALOG, max_s=20):
        say("      gmail: no add-address box")
        return STUCK
    pg.fill('[data-lucy="box"]', REPORTING_INBOX, timeout=10000)
    went = _through_google(ctx, pg, ask, say,
                           press=lambda: pg.click('[data-lucy="next"]', timeout=10000),
                           done=lambda: pg.evaluate(_FORWARD_STATE, REPORTING_INBOX) == "listed")
    return ADDED if went is True else went


def _through_google(ctx, pg, ask, say, press, done):
    """press(), then get through whatever Google puts up until done() says so.

    Seen 2026-11-17, BOTH after "Next" on our address AND after "Create filter"
    on a forwarding filter: a Gmail box "We need to verify it's you"
    (Continuar) -> a Google window with a NUMBER to tap on the owner's phone ->
    after the address, a window "forward to alphaletereporting@...?" with one
    Proceed. Lucy presses every button; the owner only taps the phone (or
    types a password, if Google asks). True once done(); else NO_TAP when
    the owner was shown a number and nothing came of it (theirs, not ours),
    STUCK otherwise (ours)."""
    popups = []
    ctx.on("page", lambda page: popups.append(page))
    press()
    told = set()
    first_phone = {}
    end = time.time() + PHONE_MAX_S
    while time.time() < end:
        for pop in [w for w in popups if not w.is_closed()]:
            try:
                text = pop.inner_text("body", timeout=3000)
            except Exception:  # noqa: BLE001 -- still loading, or just closed
                continue
            _banner(pop)
            number = _phone_number(text)
            low = text.lower()
            # Google's window says "phone" a few seconds BEFORE it shows the
            # number: "tap Yes" only when no number has come for a while, or
            # the owner gets two boxes, "Yes" then "90" (Eve's test, 11/17).
            asks_phone = "phone" in low or "teléfono" in low
            if asks_phone:
                first_phone.setdefault("at", time.time())
            no_number_yet = (not number and asks_phone and not told
                             and time.time() - first_phone["at"] >= NUMBER_GRACE_S)
            if (number and number not in told) or no_number_yet:
                _show(ask, PHONE % number if number else PHONE_NO_NUMBER)
                say("      gmail: owner asked to tap %s on their phone" % (number or "Yes"))
                told.add(number or "?")
            # "forward to alphaletereporting@... ?": its only SUBMIT is Proceed.
            if not number and REPORTING_INBOX in low:
                try:
                    if pop.evaluate(_ONE_SUBMIT):
                        pop.click('[data-lucy="proceed"]', timeout=5000)
                        say("      gmail: pressed Proceed")
                except Exception:  # noqa: BLE001 -- it closed itself
                    pass
        try:
            # Gmail's own box with no field ("verify it's you" -> Continue,
            # "confirmation link sent" -> OK): its last button goes on. FIRST:
            # our address shows behind that box, and done() alone left it up
            # on the owner's screen (Eve's test, 11/17).
            note = pg.evaluate(_NOTICE)
            if note:
                pg.click('[data-lucy="notice"]', timeout=5000)
                say("      gmail: pressed on in %r" % note[:60])
                continue
            if done():
                return True
        except Exception:  # noqa: BLE001 -- Gmail redrawing
            pass
        time.sleep(2)
    return NO_TAP if told else STUCK


def _filter_listed(pg, address: str) -> bool:
    _go(pg, address, "settings/filters")
    return bool(_wait_for(pg, _FILTER_LISTED, [SARAPLUS_SENDER, REPORTING_INBOX], max_s=25))


def _make_filter(ctx, pg, address: str, ask, say=print) -> str:
    """SaraPlus's mail -> forwarded to us. MADE only once Gmail lists it."""
    if _filter_listed(pg, address):
        return MADE
    screen = "create-filter/from=" + quote(SARAPLUS_SENDER, safe="")
    _go(pg, address, screen)
    if _wait_for(pg, _PANEL, SARAPLUS_SENDER, want=lambda v: v == "step1", max_s=15) != "step1":
        pg.goto(gmail_url(address, screen), wait_until="domcontentloaded", timeout=60000)
        _banner(pg)
    step = ""
    for _ in range(3):                 # the first press does not always take
        if _wait_for(pg, _PANEL, SARAPLUS_SENDER, want=lambda v: v == "step1", max_s=30) != "step1":
            break
        pg.click('[data-lucy="create"]', timeout=10000)
        step = _wait_for(pg, _PANEL, SARAPLUS_SENDER, want=lambda v: str(v).startswith("step2"), max_s=8) or ""
        if str(step).startswith("step2"):
            break
    if not str(step).startswith("step2"):
        say("      gmail: the filter box never reached its second step")
        return STUCK
    lists = int(str(step).split(":")[1])
    for n in range(lists):
        pg.click('[data-lucy-list="%d"]' % n, timeout=10000)
        time.sleep(0.8)
        if not pg.evaluate(_OUR_OPTION, REPORTING_INBOX):
            pg.keyboard.press("Escape")
            continue
        pg.click('[data-lucy="option"]', timeout=10000)
        ticked = pg.evaluate(_ITS_BOX, n)
        if ticked is False:
            # The real box sits OFF-SCREEN under Gmail's drawn one (a mouse
            # press can't reach it, 11/17): tick it from the page itself.
            pg.evaluate("() => document.querySelector('[data-lucy=\"forward\"]').click()")
        if pg.evaluate(_ITS_BOX, n) is not True:
            say("      gmail: the forward box would not tick")
            return STUCK
        break
    else:
        return NOT_ACCEPTED            # Gmail doesn't offer our address yet
    if pg.evaluate(_PANEL, SARAPLUS_SENDER) == "none":
        return STUCK
    went = _through_google(ctx, pg, ask, say,
                           press=lambda: pg.click('[data-lucy="create"]', timeout=10000),
                           done=lambda: pg.evaluate(_PANEL, SARAPLUS_SENDER) == "none")
    time.sleep(3)
    if _filter_listed(pg, address):
        return MADE
    return went if went is not True else STUCK


def _session(address: str, ask, say, work, introduce: bool) -> str:
    """Open Lucy's Gmail window, get the owner signed in, run work(ctx, pg)."""
    try:
        from patchright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 -- the hand steps still work
        return NO_BROWSER
    if introduce:
        ask.message(SIGN_IN % address)
    try:
        with sync_playwright() as p:
            ctx = _launch(p)
            # Gmail's "open email links?" ask comes from this call: a no-op.
            _quiet(ctx.add_init_script,
                   "try { navigator.registerProtocolHandler = function () {}; } catch (e) {}")
            try:
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()
                pg.goto(gmail_url(address, "inbox"), wait_until="domcontentloaded",
                        timeout=60000)
                if _wait_signed_in(pg, address, max_s=8):
                    pg.goto(signin_url(address), wait_until="domcontentloaded", timeout=60000)
                    why = _wait_signed_in(pg, address, bar=True)
                    if why:
                        return why
                _banner(pg)
                return work(ctx, pg)
            finally:
                _quiet(ctx.close)
    except Exception as e:  # noqa: BLE001 -- never into a setup
        say("      gmail window: %s: %s" % (type(e).__name__, str(e)[:120]))
        return STUCK


def add_and_filter(ask, address: str, confirmed, say=print, introduce: bool = True):
    """The whole forward in ONE window: add our address, wait while
    confirmed() says Gmail's mail was accepted (Lucy 1), make the filter.
    Answers (what the add said, what the filter said or None if never tried).
    confirmed() returning a str stops there and that str is the second answer."""
    out = {"filter": None}

    def work(ctx, pg):
        got = _add_address(ctx, pg, address, ask, say)
        if got not in (ADDED, ALREADY):
            return got
        _banner(pg, BANNER_WAITING)
        ok = confirmed()
        if ok is not True:
            out["filter"] = ok if isinstance(ok, str) else NOT_ACCEPTED
            return got
        # The page open since before the confirmation still thinks our
        # address is unconfirmed and won't offer it to the filter (Eve's
        # test, 11/17: "address not accepted yet" a minute after Lucy 1
        # confirmed). A fresh Gmail knows; one more after a pause if not.
        for wait_s in (0, 30):
            time.sleep(wait_s)
            _reload(pg, address)
            out["filter"] = _make_filter(ctx, pg, address, ask, say)
            if out["filter"] != NOT_ACCEPTED:
                break
        return got

    _banner_detail["text"] = BANNER_DETAIL
    added = _session(address, ask, say, work, introduce=introduce)
    return added, out["filter"]


def add_forward(ask, address: str, say=print) -> str:
    """The owner signs in; Lucy adds our address. ADDED / ALREADY, or a reason."""
    return _session(address, ask, say, lambda ctx, pg: _add_address(ctx, pg, address, ask, say),
                    introduce=True)


def make_filter(ask, address: str, say=print) -> str:
    """After Gmail confirmed: Lucy makes the filter. MADE, or a reason. The
    sign-in is normally still saved from add_forward, so nothing is asked."""
    return _session(address, ask, say, lambda ctx, pg: _make_filter(ctx, pg, address, ask, say),
                    introduce=False)


def available() -> bool:
    try:
        import patchright  # noqa: F401
        return platform.system() in ("Darwin", "Windows")
    except Exception:  # noqa: BLE001
        return False
