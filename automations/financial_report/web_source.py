"""Pull the weekly financials from Double Entry (doubleentry.com).

Until 2026-08 this section was fed by .xlsx workbooks that three senders emailed
in (see email_source.py) — the report could only run once enough books had
landed, and a sender who forgot left their ICDs blank. The numbers now live on
Double Entry's ORG SUMMARY REPORT, so we take them from the source instead:
nothing to wait for, nothing to upload.

AUTH — username + password from the gitignored creds file (`creds.doubleentry_*`),
NEVER hardcoded. But the password alone does NOT get you in: Double Entry emails
a 6-digit OTP on EVERY sign-in and parks you on /auth/verify-email until you
enter it. There's no "trust this device" that skips it.

That would normally kill unattended running — except the OTP lands in
alphaletereporting@gmail.com, the same inbox the scheduled reports already read
over IMAP (shared/email_ingest). So the login reads its own code out of the
mailbox and types it: login -> wait for the mail -> 6 digits -> in. No human,
and no cookie-replay session to go stale (which is what Credico/ownerville have
to live with).

The one thing that WILL break this: if the OTP is ever re-pointed at another
address. `check_login()` is the probe that says so out loud — it's what
`lucy set_doubleentry_creds` runs to verify an install.
"""
from __future__ import annotations

import datetime as dt
import email as _email
import re
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime

from automations.shared import creds

BASE = "https://www.doubleentry.com"
LOGIN_URL = f"{BASE}/auth/login"
REPORT_URL = f"{BASE}/org-summary-report"

# How long to let the sign-in POST + redirect settle before calling it a failure.
_LOGIN_TIMEOUT_MS = 30_000

# --- the OTP mail -----------------------------------------------------------
# Sender + subject are stable ("Your One-Time OTP | Double Entry" from
# DoNotReply@doubleentry.com). The body carries exactly one 6-digit run, so the
# code is unambiguous; the mail says it's good for 10 minutes.
_OTP_SENDER = "doubleentry.com"
_OTP_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
# Delivery is usually a few seconds. Wait generously — the code stays valid for
# 10 min, so a slow mail is worth waiting out rather than failing the run.
_OTP_WAIT_S = 180
_OTP_POLL_S = 5


def _otp_mails() -> list:
    """(sent_at, body) for every Double Entry OTP mail from the last 2 days,
    oldest first. Reconnects on each call — a readonly IMAP session doesn't
    surface mail that arrives after its SELECT, which is exactly the mail we're
    waiting for."""
    from automations.shared import email_ingest
    out = []
    M = email_ingest._connect()
    try:
        since = (dt.date.today() - dt.timedelta(days=2)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(FROM "{_OTP_SENDER}" SINCE {since})')
        for mid in (data[0] or b"").split():
            typ, d = M.fetch(mid, "(RFC822)")
            if not d or not d[0]:
                continue
            msg = _email.message_from_bytes(d[0][1])
            try:
                sent = parsedate_to_datetime(msg["Date"])
            except Exception:  # noqa: BLE001 — a malformed Date shouldn't kill the poll
                continue
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=dt.timezone.utc)
            out.append((sent, _mail_text(msg)))
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return sorted(out, key=lambda t: t[0])


def _mail_text(msg) -> str:
    """Readable text for an OTP mail — text/plain if present, else tags stripped
    from the HTML part (Double Entry sends both)."""
    plain = html = ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_payload(decode=True).decode(
                part.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/plain" and not plain:
            plain = body
        elif ctype == "text/html" and not html:
            html = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", plain or html).strip()


def _newest_otp_at():
    """When the most recent OTP mail arrived, or None if there are none.

    Taken BEFORE submitting the login so we can wait for a code STRICTLY newer
    than it. Anchoring on the mailbox instead of the local clock means clock
    skew between this machine and Gmail can't make us grab a stale code and
    burn the attempt."""
    mails = _otp_mails()
    return mails[-1][0] if mails else None


def _await_otp(after, *, verbose: bool = True) -> str:
    """Block until an OTP mail newer than `after` lands; return its 6 digits.

    Raises when none arrives in time — with the actionable cause, since the
    realistic reason is that the code now goes to a different mailbox."""
    deadline = time.monotonic() + _OTP_WAIT_S
    while time.monotonic() < deadline:
        for sent, body in reversed(_otp_mails()):
            if after is not None and sent <= after:
                break            # sorted — everything older follows
            m = _OTP_RE.search(body)
            if m:
                if verbose:
                    print(f"-> doubleentry: OTP received ({sent:%H:%M:%S})",
                          flush=True)
                return m.group(0)
        time.sleep(_OTP_POLL_S)
    from automations.shared.email_ingest import ACCOUNT
    raise RuntimeError(
        f"no Double Entry OTP reached {ACCOUNT} within {_OTP_WAIT_S}s. Either "
        "mail is delayed, or the code is now sent to a different address — "
        "check the account's registered email.")


def _submit_otp(page, code: str, *, verbose: bool = True) -> None:
    """Type the code into the 6 single-character boxes and submit.

    The boxes are a React OTP widget: `fill` on each one dispatches the input
    events it listens for. Typing into the first and relying on auto-advance
    also works, but drops digits when a re-render steals focus mid-type — so
    fill each box explicitly.

    The widget SUBMITS ITSELF the moment the sixth digit lands (the button flips
    to a disabled 'Verifying…' and the node detaches on navigation), so clicking
    is only a fallback for when it doesn't."""
    boxes = page.locator("input[maxlength='1']")
    n = boxes.count()
    if n < len(code):
        raise RuntimeError(f"expected {len(code)} OTP boxes on the verify page, "
                           f"found {n}")
    for i, digit in enumerate(code):
        boxes.nth(i).fill(digit)
    page.wait_for_timeout(2500)          # give the auto-submit a chance
    if "/auth/verify-email" in (page.url or ""):
        try:
            btn = page.get_by_role("button", name=re.compile("verify", re.I))
            if btn.is_enabled(timeout=2000):
                btn.click()
        except Exception:  # noqa: BLE001 — already submitting/navigating
            pass
    try:
        page.wait_for_url(lambda u: "/auth/verify-email" not in u,
                          timeout=_LOGIN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — the caller's URL check is the verdict
        pass
    page.wait_for_timeout(2000)
    if verbose:
        print(f"-> doubleentry: OTP accepted ({page.url})", flush=True)


def _login(page, *, verbose: bool = True) -> bool:
    """Sign in on `page`. True once we're off the login screen.

    Selectors are matched by ROLE/placeholder rather than generated class names —
    the form is React-rendered, so its classes churn between deploys while the
    'email or mobile number' placeholder and the submit button have held.
    """
    page.goto(f"{LOGIN_URL}?redirect=%2Forg-summary-report",
              wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    user = creds.doubleentry_username()
    if verbose:
        # Log WHO, never the password — and its length, which is the diagnostic
        # that tells you a paste went wrong without leaking the value.
        print(f"-> doubleentry: signing in as {user} "
              f"({len(creds.doubleentry_password())} char password)", flush=True)
    page.fill("input[placeholder*='email' i]", user)
    page.fill("input[type=password]", creds.doubleentry_password())
    # Note the newest OTP in the mailbox BEFORE submitting, so the code we wait
    # for is provably the one this sign-in triggered.
    otp_baseline = _newest_otp_at()
    page.click("button[type=submit]")
    try:
        page.wait_for_url(lambda u: "/auth/login" not in u,
                          timeout=_LOGIN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — the URL check below is the real verdict
        pass
    page.wait_for_timeout(2000)
    # Password accepted -> Double Entry parks us here until the emailed code is
    # entered. Every sign-in hits this; there's no remembered device.
    if "/auth/verify-email" in (page.url or ""):
        if verbose:
            print("-> doubleentry: OTP required, reading it from the inbox…",
                  flush=True)
        _submit_otp(page, _await_otp(otp_baseline, verbose=verbose),
                    verbose=verbose)
    ok = not any(p in (page.url or "")
                 for p in ("/auth/login", "/auth/verify-email"))
    if verbose:
        print(f"-> doubleentry: {'logged in' if ok else 'LOGIN FAILED'} "
              f"({page.url})", flush=True)
    return ok


def _login_error(page) -> str:
    """Whatever the page says about a rejected sign-in — the inline validation
    error if there is one, else a trimmed slice of the body. Used to tell
    'wrong password' apart from 'a second factor appeared', which decides
    whether unattended running is possible at all."""
    for sel in ("[role=alert]", ".error", "[class*='error' i]"):
        try:
            node = page.locator(sel).first
            if node.count() and (txt := (node.inner_text() or "").strip()):
                return txt[:200]
        except Exception:  # noqa: BLE001
            continue
    try:
        return " ".join((page.inner_text("body") or "").split())[:200]
    except Exception:  # noqa: BLE001
        return "(no readable page text)"


@contextmanager
def session(*, headless: bool = True, verbose: bool = True):
    """Yield a logged-in page sitting on the ORG SUMMARY REPORT.

    Raises with the page's own error text when the login is rejected, so a
    failure names the cause (expired password / a new second factor) instead of
    surfacing later as an empty parse.
    """
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000},
                                  accept_downloads=True)
        page = ctx.new_page()
        try:
            if not _login(page, verbose=verbose):
                raise RuntimeError(
                    "Double Entry login rejected — the page says: "
                    f"{_login_error(page)!r}. Check doubleentry_username / "
                    "doubleentry_password in ownerville-creds.json.")
            page.goto(REPORT_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            yield page
        finally:
            ctx.close()
            browser.close()


# --- the data ---------------------------------------------------------------
# The page is a thin client over a JSON API, so we read the API rather than
# scrape the rendered table: no layout to break, values unrounded, and the week
# boundaries come back declared (`ranges`) instead of inferred from a header row.
API = "https://api.doubleentry.com"
_OWNERS_EP = f"{API}/client/org-summary/search/promoting-owner"
_SUMMARY_EP = f"{API}/client/org-summary"


def _api_token(page, *, verbose: bool = True) -> str:
    """The Bearer token the app sends to api.doubleentry.com.

    Sniffed off a live request rather than read from storage: it isn't in
    localStorage (the SPA keeps it in memory), so the request header is the only
    place it's reliably visible. Re-navigating the report page is what makes one
    happen."""
    seen: list = []
    page.on("request", lambda r: (seen.append(r.all_headers().get("authorization"))
                                  if API in r.url else None))
    page.goto(REPORT_URL, wait_until="domcontentloaded")
    for _ in range(30):
        page.wait_for_timeout(500)
        tok = next((t for t in seen if t), None)
        if tok:
            if verbose:
                print(f"-> doubleentry: API token captured ({len(tok)} chars)",
                      flush=True)
            return tok
    raise RuntimeError("never saw an authenticated API request — the org summary "
                       "page didn't load its data")


def _get(page, url: str, token: str) -> dict:
    r = page.request.get(url, headers={"authorization": token})
    if not r.ok:
        raise RuntimeError(f"GET {url.split('?')[0]} -> HTTP {r.status}")
    return r.json()["data"]


def fetch_offices(*, date: "str | None" = None, verbose: bool = True):
    """Every office's financials, in the SAME shape parse.parse_financial_files
    returns: (by_owner, weeks, problems).

    That's deliberate — run.py and fill.py can't tell which source they're on,
    so swapping email for web changes one call and nothing downstream.

    `date` is the week-ending the report is anchored to (YYYY-MM-DD); the API
    answers with that week plus the three before it. Defaults to the most recent
    closed week, matching what the page opens on.
    """
    from automations.financial_report.parse import (_num, _owner_from_office,
                                                    _state_from_office, norm_name)
    date = date or _default_week_end().isoformat()
    by_owner: dict = {}
    problems: list = []
    weeks: list = []
    with session(verbose=verbose) as page:
        token = _api_token(page, verbose=verbose)
        owners = _get(page, f"{_OWNERS_EP}?per_page=200&page=1", token)["items"]
        if verbose:
            print(f"-> doubleentry: {len(owners)} promoting owner(s), "
                  f"week ending {date}", flush=True)
        for o in owners:
            try:
                data = _get(page, f"{_SUMMARY_EP}?date={date}"
                                  f"&promoting_owner_id={o['id']}"
                                  f"&color_scheme=light", token)
            except Exception as e:  # noqa: BLE001 — one owner failing isn't fatal
                problems.append((f"{o['name']} (owner {o['id']})",
                                 f"summary fetch failed: {str(e)[:90]}"))
                continue
            # Week endings are declared by the API, so they're exact rather than
            # inferred — and they match the emailed books' Saturday endings.
            if not weeks:
                weeks = [dt.date.fromisoformat(r["end"]) for r in data["ranges"]]
            ends = [dt.date.fromisoformat(r["end"]) for r in data["ranges"]]
            for comp in data.get("companies", []):
                name = (comp.get("name") or "").strip()
                metrics: dict = {}
                for cat in comp.get("categories", []):
                    label = (cat.get("label") or "").strip().upper()
                    vals = cat.get("transactions") or []
                    metrics[label] = {
                        ends[i]: _num(vals[i])
                        for i in range(min(len(ends), len(vals)))
                        if vals[i] not in (None, "")}
                owner = _owner_from_office(name)
                key = norm_name(owner)
                if not key:
                    problems.append((name, "no (OWNER-STATE) in the company name"))
                    continue
                office = {"office": name, "owner": owner,
                          "state": _state_from_office(name), "metrics": metrics}
                # Same dedup rule as the email parser: one office per
                # (owner, state), so a multi-location owner keeps both.
                bucket = by_owner.setdefault(key, [])
                at = next((i for i, x in enumerate(bucket)
                           if x.get("state", "") == office["state"]), None)
                if at is None:
                    bucket.append(office)
                else:
                    bucket[at] = office
    if verbose:
        n = sum(len(v) for v in by_owner.values())
        print(f"-> doubleentry: {n} office(s) for {len(by_owner)} owner(s); "
              f"weeks {[w.isoformat() for w in weeks]}", flush=True)
    return by_owner, weeks, problems


def _default_week_end() -> dt.date:
    """The most recent CLOSED week ending (Saturday), in Central time.

    Central because every report here is anchored to the Texas business week,
    not to whatever timezone the runner happens to sit in.
    """
    try:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001 — a missing tzdata shouldn't break the run
        today = dt.date.today()
    # Mon=0 … Sat=5. Step back to the Saturday on/before today.
    return today - dt.timedelta(days=(today.weekday() - 5) % 7)


def check_login(*, headless: bool = True) -> tuple[bool, str]:
    """Probe: can THIS machine sign in and reach the org summary unattended?

    Returns (ok, one-line detail) and never raises — it's called from the
    mini-control credential install, where a crash would read as a broken
    action rather than a bad credential.
    """
    try:
        with session(headless=headless, verbose=False) as page:
            url = page.url or ""
            if "/auth/login" in url:
                return False, f"bounced back to the login screen ({url})"
            return True, f"signed in, org summary reachable ({url})"
    except Exception as e:  # noqa: BLE001 — the message IS the result
        return False, f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
