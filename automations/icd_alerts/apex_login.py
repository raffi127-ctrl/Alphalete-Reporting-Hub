"""Lucy signs into the owner's Apex BY HERSELF: password + auth-app code.

WHY (Eve + Megan, 2026-11-16). The PNL reads the owner's Apex payroll every
week. A session the owner signed into by hand dies after a while, and then
the PNL waits for him to be at the Mac. So the owner sets Apex's
"authenticator app" up ONCE with Lucy (apex_2fa_setup), and Lucy keeps three
things on THIS Mac only, in a file only this Mac's user can read:

    user name, password, the authenticator key

From the key Lucy makes the same 6-digit code a phone app would (TOTP,
RFC 6238 -- standard library, nothing to install). Apex shows "Use
Authenticator" and "Use SMS" as separate options (probe_apex_2fa, Carlos's
account, 2026-11-17), so the owner keeps his text message.

ALWAYS UNDER THE LOCK (apex_guard, "block"): the sign-in needs two writes --
the login form and the 2-step form -- and those are on the allow list; nothing
else that could change Apex leaves the browser.

NEVER HAMMERS THE LOGIN. One try per run, and after MAX_FAILS failed tries in
a row Lucy stops and says so: a wrong password tried every hour is how an
account gets locked. Saving the login again (the setup) clears the count.

Cloudflare's box in front of the form clears itself if the form waits before
it is sent (resources/lucy-login-standard.md) -- PRE_SUBMIT_WAIT_S, 30s. Never
shorten it.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import struct
import time
from typing import Dict, Optional, Tuple

from automations.icd_alerts import config as C

CREDS_PATH = C.APP_DIR / "apex-login.json"
STATE_PATH = C.APP_DIR / "apex-login-state.json"
MAX_FAILS = 2
# Bump to give every Mac a clean fail count with the next release (there is no
# remote "reset"). 2: Jairo stopped 2026-11-24 "failed at code box" with no
# trace of the screen -- one more round, now saying what the page showed.
FAIL_ROUND = 3     # 3: 11/24 the screen was SendCode 'Select Verification Method'
PRE_SUBMIT_WAIT_S = 30        # the login standard: the pause IS the fix
STEP_S = 30
FRESH_S = 5                   # a code with less life left than this: wait for the next


# --- the code ----------------------------------------------------------------
def clean_key(raw: str) -> str:
    """'taop ccrx ...' -> 'TAOPCCRX...'. Raises ValueError if it is not a key."""
    k = re.sub(r"[\s-]", "", raw or "").upper()
    if len(k) < 16 or not re.fullmatch(r"[A-Z2-7]+=*", k):
        raise ValueError("not an authenticator key")
    base64.b32decode(k + "=" * (-len(k) % 8))      # proves it decodes
    return k


def totp(key: str, now: Optional[float] = None, digits: int = 6) -> str:
    """The code an authenticator app shows for `key` at `now` (RFC 6238, SHA1)."""
    k = clean_key(key)
    secret = base64.b32decode(k + "=" * (-len(k) % 8))
    counter = int((time.time() if now is None else now) // STEP_S)
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(n).zfill(digits)


def fresh_code(key: str, now=time.time, sleep=time.sleep) -> str:
    """A code with at least FRESH_S seconds left, so it is still good when Apex
    reads it."""
    left = STEP_S - (now() % STEP_S)
    if left < FRESH_S:
        sleep(left + 0.5)
    return totp(key, now())


_KEY_ON_PAGE = re.compile(r"enter this key\s+(.+?)\s+into your", re.I | re.S)


def key_from_page(text: str) -> str:
    """The key Apex prints on its 'Configure authenticator app' page."""
    m = _KEY_ON_PAGE.search(text or "")
    if not m:
        raise ValueError("no key on the page")
    return clean_key(m.group(1))


# --- the login, on this Mac only ----------------------------------------------
def save_creds(username: str, password: str, key: str) -> None:
    C.app_dir()
    CREDS_PATH.write_text(json.dumps({"username": username, "password": password,
                                      "totp_key": clean_key(key)}))
    try:
        CREDS_PATH.chmod(0o600)
    except OSError:
        pass
    _save_state({})          # a new login starts with a clean count


def creds() -> Dict[str, str]:
    try:
        d = json.loads(CREDS_PATH.read_text())
    except (OSError, ValueError):
        return {}
    if not (d.get("username") and d.get("password") and d.get("totp_key")):
        return {}
    return d


def _state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(s: Dict) -> None:
    try:
        C.app_dir()
        STATE_PATH.write_text(json.dumps(s))
    except OSError:
        pass


def _fails(s: Dict) -> int:
    """Failures counted in THIS round; an older round's count is void."""
    if int(s.get("round") or 1) != FAIL_ROUND:
        return 0
    return int(s.get("fails") or 0)


def stopped() -> bool:
    """Too many failed sign-ins in a row: wait for a person."""
    return _fails(_state()) >= MAX_FAILS


def _record(ok: bool, step: str) -> None:
    s = _state()
    s["fails"] = 0 if ok else _fails(s) + 1
    s["round"] = FAIL_ROUND
    s["last"] = "%s %s" % (dt.datetime.now().isoformat(timespec="minutes"),
                           "ok" if ok else "failed at " + step)
    _save_state(s)


# --- the page ------------------------------------------------------------------
_USER = ('input[name*="user" i]:visible, input[name*="email" i]:visible, '
         'input[type="email"]:visible, input[id*="user" i]:visible')
_PASS = 'input[type="password"]:visible'
_CODE = ('input[name*="code" i]:visible, input[autocomplete="one-time-code"]:visible, '
         'input[id*="code" i]:visible')
_REMEMBER = 'input[type="checkbox"][name*="remember" i]'
_SUBMIT = 'button[type="submit"]:visible, input[type="submit"]:visible'
_PICK_APP = re.compile(r"use authenticator|authenticator app", re.I)
# Apex's /Identity/Account/SendCode ("Select Verification Method" + Next,
# Jairo's Mac 2026-11-24): pick the code app, never the text/phone/email one
# (that would text the owner a code he did not ask for).
_APP_OPTION = re.compile(r"authenticator|auth app|code app|app|totp", re.I)
_NOT_APP = re.compile(r"sms|text|phone|email|e-mail|call", re.I)


def pick_method(page) -> Optional[str]:
    """On a choose-the-method screen: choose the code app and press Next.
    None = not that screen. 'picked' = done. Anything else = why it did not
    pick (the options seen) -- nothing was pressed then."""
    opts = page.evaluate(r"""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const out = [];
      document.querySelectorAll('select').forEach((s, si) => { if (vis(s))
        Array.from(s.options).forEach(o => out.push({kind: 'select', si: si,
          value: o.value, text: (o.text || '').trim()})); });
      document.querySelectorAll('input[type=radio]').forEach((r, ri) => { if (vis(r) || (r.labels && r.labels[0] && vis(r.labels[0]))) {
        const lab = (r.labels && r.labels[0] ? r.labels[0].innerText : '') || '';
        out.push({kind: 'radio', ri: ri, value: r.value, text: lab.trim()}); }});
      return out;
    }""")
    if not opts:
        return None
    good = [o for o in opts
            if _APP_OPTION.search("%s %s" % (o["text"], o["value"]))
            and not _NOT_APP.search("%s %s" % (o["text"], o["value"]))]
    if not good:
        return "no code-app option (options: %s)" % ", ".join(
            (o["text"] or o["value"])[:30] for o in opts)[:150]
    o = good[0]
    if o["kind"] == "select":
        page.locator("select").nth(o["si"]).select_option(value=o["value"])
    else:
        page.locator("input[type=radio]").nth(o["ri"]).check(force=True)
    nxt = page.locator(_SUBMIT)
    if nxt.count():
        nxt.first.click()
    else:
        page.get_by_role("button", name=re.compile(r"next|send|continue", re.I)).first.click()
    return "picked"


def _past_login(page) -> bool:
    try:
        return page.locator('a[href="/payrolls"]').count() > 0
    except Exception:  # noqa: BLE001 -- mid-navigation
        return False


def where(page, limit: int = 220) -> str:
    """What screen the sign-in is on -- path, headings, buttons. Never what is
    typed in a box (no input values are read), so it can go in a fault line."""
    try:
        from urllib.parse import urlparse
        path = urlparse(page.url).path or "/"
        bits = page.evaluate(r"""() => {
          const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
          const t = e => (e.innerText || e.value || e.getAttribute('aria-label') || '')
                           .replace(/\s+/g, ' ').trim().slice(0, 50);
          const pick = (sel, n, val) => Array.from(document.querySelectorAll(sel))
             .filter(vis).map(e => val && e.tagName === 'INPUT' && e.type !== 'submit'
                                    ? (e.name || e.id || e.type) : t(e))
             .filter(Boolean).slice(0, n);
          return {
            say: pick('h1,h2,h3,h4,.alert,.validation-summary-errors,[role=alert]', 5),
            btn: pick('button,input[type=submit],a.btn', 5),
            box: pick('input:not([type=hidden])', 5, true),
            opt: Array.from(document.querySelectorAll('select option'))
                   .map(o => (o.text || '').trim()).filter(Boolean).slice(0, 5),
          };
        }""")
        out = "page %s" % path
        if bits.get("say"):
            out += " says '%s'" % "' / '".join(bits["say"])
        if bits.get("btn"):
            out += "; buttons: %s" % ", ".join(bits["btn"])
        if bits.get("opt"):
            out += "; choices: %s" % ", ".join(bits["opt"])
        if bits.get("box"):
            out += "; boxes: %s" % ", ".join(bits["box"])
        return out[:limit]
    except Exception as e:  # noqa: BLE001 -- best effort, never blocks
        return "page unknown (%s)" % type(e).__name__


def _submit(page, field) -> None:
    btn = page.locator(_SUBMIT)
    if btn.count():
        btn.first.click()
    else:
        field.press("Enter")


def sign_in(page, login: Dict[str, str], *, wait_s: int = PRE_SUBMIT_WAIT_S,
            log=print) -> Tuple[bool, str]:
    """From the Apex login form to signed in. (ok, step) -- `step` names where
    it stopped, never a value. One try; the caller checks stopped() first."""
    from automations.carlos_payroll_pull import run as AP

    step = "open"
    try:
        page.goto(AP.APEX_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        if _past_login(page):
            _record(True, step)
            return True, "already signed in"
        step = "user name box"
        user = page.locator(_USER).first
        user.wait_for(state="visible", timeout=30_000)
        user.fill(login["username"])
        step = "password box"
        pw = page.locator(_PASS).first
        if not pw.count() or not pw.is_visible():
            # user name first, then the password (the OwnerVille shape)
            _submit(page, user)
            pw.wait_for(state="visible", timeout=30_000)
        pw.fill(login["password"])
        page.wait_for_timeout(wait_s * 1000)        # Cloudflare clears itself
        _submit(page, pw)
        step = "after password"
        picked = False
        for _ in range(30):                         # up to ~60s
            page.wait_for_timeout(2000)
            if _past_login(page) or page.locator(_CODE).count():
                break
            pick = page.get_by_text(_PICK_APP)
            if pick.count() and pick.first.is_visible():
                step = "choosing the app code"
                pick.first.click()
                continue
            if not picked:
                how = pick_method(page)
                if how == "picked":
                    picked = True
                    step = "after choosing the code app"
                elif how:
                    step = "choosing the method: " + how
                    raise RuntimeError(how)
        if not _past_login(page):
            step = "code box"
            code = page.locator(_CODE).first
            code.wait_for(state="visible", timeout=20_000)
            code.fill(fresh_code(login["totp_key"]))
            rem = page.locator(_REMEMBER)
            if rem.count():
                try:
                    rem.first.check()
                except Exception:  # noqa: BLE001 -- nice to have
                    pass
            _submit(page, code)
            step = "after code"
            for _ in range(20):
                page.wait_for_timeout(2000)
                if _past_login(page):
                    break
        ok = _past_login(page)
    except Exception as e:  # noqa: BLE001
        log("apex sign-in: stopped at %s (%s)" % (step, type(e).__name__))
        ok = False
    if not ok:
        step = "%s [%s]" % (step, where(page))
    _record(ok, step)
    return ok, ("signed in" if ok else "failed at " + step)
