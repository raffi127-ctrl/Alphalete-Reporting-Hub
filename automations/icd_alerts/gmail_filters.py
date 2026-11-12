"""One Google "Allow", and Lucy makes the Gmail filter herself.

WHY (Megan 2026-11-12: "since we're doing the google allow can we make the
forwarding and filters for them?"). Every code forward ended on Gmail's
#create-filter screen with four clicks for the owner to get right. Gmail's API
can create that filter, with the owner's permission, so now:

  owner clicks Allow once -> Lucy makes the exact filter -> Lucy reads Gmail's
  filters back to check it is there -> the permission is thrown away (revoked).

If they don't allow it, or anything on Google's side says no, the caller shows
the old hand-built steps. Nothing here ever raises into a setup.

WHAT LUCY CAN'T DO: add the forwarding ADDRESS. Google keeps that for Workspace
admins, so the owner still types it in, and Lucy 1 still confirms it
(code_answer.confirm_forwards). A filter can only forward to an address Gmail
calls "accepted", so this is the last step, never the first.

PROVEN LIVE first in the laptop walkthrough (laptop_setup, 2026-11-12). What it
taught, all kept here:
  * The Google app is the repo's own desktop client (oauth-client.json,
    "Recruiting Report"). It's unverified, so Google shows "Google hasn't
    verified this app": Advanced -> "Go to Recruiting Report (unsafe)".
  * Consent comes in two pages, and on the second the Gmail item has a box
    that must be TICKED. Unticked, the token comes back without
    gmail.settings.basic and every read is a 403 -- so the granted scope is
    checked and, if it's missing, Lucy asks again.
  * forwardingAddresses / filters answer 204 with no body when there are none.
    That's "none", not an error.

THE CLIENT IS FETCHED, NOT SHIPPED. package.py keeps the Hub repo's files off
ICD machines on purpose; this one is public already (Google treats a desktop
client's secret as non-confidential), so it is read from GitHub at the moment
of the Allow, like the laptop walkthrough does. No token is ever written down.

STDLIB ONLY, like relay.py: runs on the office Mac or Windows PC.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

CLIENT_URL = ("https://raw.githubusercontent.com/raffi127-ctrl/"
              "Alphalete-Reporting-Hub/main/oauth-client.json")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me/settings/"
SETTINGS_SCOPE = "https://www.googleapis.com/auth/gmail.settings.basic"
SCOPES = (SETTINGS_SCOPE, "email")

WAIT_AFTER_OK_S = 120      # Google's page can still be open when they press OK
TRIES = 3                  # the Gmail box left unticked, asked again

ALLOW_STEPS = (
    "Lucy will make the Gmail filter for you.\n\n"
    "A Google page just opened. IT WILL LOOK LIKE AN ERROR. IT'S NOT. "
    "Google shows this for small companies' apps. This one is ours.\n\n"
    "1. Pick: %s\n"
    "2. You'll see \"Google hasn't verified this app\". "
    "Do NOT click the big \"Back to safety\" button.\n"
    "3. Look at the BOTTOM LEFT for the small word \"Advanced\". Click it.\n"
    "4. More words show up. At the BOTTOM LEFT, click the small link "
    "\"Go to Recruiting Report (unsafe)\".\n"
    "5. Next page: Tick the box next to Gmail (or \"Select all\"). "
    "Skip this and it won't work.\n"
    "6. Click \"Continue\".\n\n"
    "Then click OK here.")
UNTICKED = ("Almost! The Gmail box wasn't ticked.\n\n"
            "Lucy will open the Google page again. Do the same clicks: the small "
            "\"Advanced\" at the bottom left, then the small \"Go to Recruiting "
            "Report (unsafe)\" link.\n\n"
            "This time tick the box next to Gmail (or \"Select all\"), then click "
            "\"Continue\".")
WRONG_ACCOUNT = ("That was %s, but the emails go to %s.\n\n"
                 "Lucy will open the Google page again. Please pick %s.")
WAITING = "Waiting for Google... Finish the Google page, then this closes by itself."
DONE_PAGE = ("<!doctype html><meta charset='utf-8'><title>Done</title>"
             "<body style='font:22px -apple-system,Segoe UI,sans-serif;padding:40px'>"
             "&#9989; Done. You can close this tab and go back to Lucy.</body>")

# What set_up() returns.
MADE = "made"                 # every filter is there, read back from Gmail
DECLINED = "declined"         # no Allow (closed the page, said no, ran out of time)
NOT_ACCEPTED = "forward not accepted yet"
FAILED = "failed"             # Google or the network said no


class Want:
    """One filter: mail matching these words, forwarded to `to`. Empty words
    mean "not set", and a filter only counts as ours if it has EXACTLY these
    words -- Sterling's old subject-only filter is not the one-filter design."""

    KEYS = ("from", "to", "subject", "query", "negatedQuery")

    def __init__(self, to: str, name: str, **criteria: str):
        self.to = to.strip().lower()
        self.name = name
        self.criteria = {k: v for k, v in criteria.items() if v}

    def body(self) -> Dict:
        return {"criteria": dict(self.criteria), "action": {"forward": self.to}}

    def matches(self, f: Dict) -> bool:
        have = f.get("criteria") or {}
        fwd = str((f.get("action") or {}).get("forward") or "").strip().lower()
        if fwd != self.to:
            return False
        return all(_norm(have.get(k)) == _norm(self.criteria.get(k))
                   for k in self.KEYS)


def _norm(v) -> str:
    return str(v or "").strip().lower()


# --- HTTP (stdlib) -------------------------------------------------------------
def _ctx():
    try:
        from automations.icd_alerts import relay as R
        return R._ssl_context()
    except Exception:  # noqa: BLE001
        import ssl
        return ssl.create_default_context()


def _call(url: str, data: Optional[bytes] = None, token: str = "",
          json_body: Optional[Dict] = None, method: str = "") -> Tuple[int, Dict]:
    """(HTTP status, JSON body). 204 / no body -> {}. Never raises: a network
    failure is status 0."""
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read() or b"", e.code
    except Exception:  # noqa: BLE001
        return 0, {}
    try:
        return code, (json.loads(raw.decode("utf-8")) if raw.strip() else {})
    except ValueError:
        return code, {}


def _client() -> Tuple[str, str]:
    code, body = _call(CLIENT_URL)
    inst = body.get("installed") or {}
    return str(inst.get("client_id") or ""), str(inst.get("client_secret") or "")


# --- the Allow -------------------------------------------------------------------
class _Catch(http.server.BaseHTTPRequestHandler):
    """Catches Google's redirect on 127.0.0.1. Anything without a state (the
    browser's favicon ask) is answered and ignored. A connection that sends
    nothing (a browser warming one up) is dropped after 5 seconds."""

    timeout = 5

    def do_GET(self):  # noqa: N802 -- http.server's name
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "state" in q:
            self.server.got = {k: v[0] for k, v in q.items()}
        body = DONE_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


class Grant:
    """A short-lived Gmail-settings permission. revoke() throws it away."""

    def __init__(self, token: str, email: str):
        self.token, self.email = token, email.strip().lower()

    def get(self, path: str) -> Tuple[int, Dict]:
        return _call(GMAIL + path, token=self.token)

    def post(self, path: str, body: Dict) -> Tuple[int, Dict]:
        return _call(GMAIL + path, token=self.token, json_body=body)

    def revoke(self) -> None:
        if self.token:
            _call(REVOKE_URL, data=urllib.parse.urlencode(
                {"token": self.token}).encode("ascii"))
        self.token = ""


def _open(url: str, say=print) -> None:
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        say("      open %s" % url)


def _ask_once(ask, account: str, say=print, wait_s: int = WAIT_AFTER_OK_S
              ) -> Tuple[str, Optional[Grant]]:
    """One trip to Google's page. ("ok", grant) | ("unticked", None) |
    ("declined", None) | ("failed", None)."""
    cid, secret = _client()
    if not cid:
        return "failed", None
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Catch)
    srv.got, srv.timeout = None, 1
    port = srv.server_address[1]
    redirect = "http://127.0.0.1:%d" % port
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    stop = threading.Event()

    def serve():
        while not stop.is_set() and srv.got is None:
            srv.handle_request()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        _open(AUTH_URL + "?" + urllib.parse.urlencode({
            "response_type": "code", "access_type": "online", "prompt": "consent",
            "client_id": cid, "redirect_uri": redirect, "state": state,
            "login_hint": account, "scope": " ".join(SCOPES),
            "code_challenge": challenge, "code_challenge_method": "S256"}), say)
        ask.message(ALLOW_STEPS % account)
        deadline = time.time() + wait_s
        hold = getattr(ask, "hold", None)
        while srv.got is None and time.time() < deadline:
            if hold:
                hold(WAITING, 10)
            if srv.got is None:
                time.sleep(1)
    finally:
        stop.set()
        t.join(3)
        srv.server_close()
    got = srv.got or {}
    if got.get("state") != state or not got.get("code"):
        return "declined", None
    code, tok = _call(TOKEN_URL, data=urllib.parse.urlencode({
        "code": got["code"], "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
        "code_verifier": verifier}).encode("ascii"))
    token = str(tok.get("access_token") or "")
    if not token:
        return "failed", None
    grant = Grant(token, "")
    if SETTINGS_SCOPE not in str(tok.get("scope") or "").split():
        grant.revoke()
        return "unticked", None
    _c, me = _call(USERINFO_URL, token=token)
    grant.email = str(me.get("email") or "").strip().lower()
    return "ok", grant


def allow(ask, account: str, say=print) -> Optional[Grant]:
    """Ask for the permission, for THAT account, asking again when the Gmail
    box was left unticked or another account was picked. None = no Allow."""
    account = account.strip().lower()
    for _ in range(TRIES):
        word, grant = _ask_once(ask, account, say)
        if word == "unticked":
            ask.message(UNTICKED)
            continue
        if word != "ok":
            return None
        if grant.email and account and grant.email != account:
            other = grant.email
            grant.revoke()
            ask.message(WRONG_ACCOUNT % (other, account, account))
            continue
        return grant
    return None


# --- what Lucy does with it --------------------------------------------------------
def forward_status(g: Grant, to: str) -> str:
    """'accepted' | 'pending' | '' (not added) | 'unreadable'."""
    code, body = g.get("forwardingAddresses")
    if code not in (200, 204):
        return "unreadable"
    for a in body.get("forwardingAddresses") or []:
        if _norm(a.get("forwardingEmail")) == _norm(to):
            return str(a.get("verificationStatus") or "")
    return ""


def filters(g: Grant) -> Optional[List[Dict]]:
    code, body = g.get("filters")
    if code not in (200, 204):
        return None
    return list(body.get("filter") or [])


def missing(have: Sequence[Dict], wants: Sequence[Want]) -> List[Want]:
    return [w for w in wants if not any(w.matches(f) for f in have)]


def make(g: Grant, wants: Sequence[Want], say=print) -> str:
    """Make the filters that aren't there, then read them all back."""
    for to in sorted({w.to for w in wants}):
        st = forward_status(g, to)
        if st == "unreadable":
            return FAILED
        if st != "accepted":
            return NOT_ACCEPTED
    have = filters(g)
    if have is None:
        return FAILED
    for w in missing(have, wants):
        code, _b = g.post("filters", w.body())
        if code != 200:
            say("      filter %s: Google said %s" % (w.name, code or "no answer"))
    have = filters(g)
    if have is None or missing(have, wants):
        return FAILED
    for w in wants:
        say("      Lucy made the filter: %s" % w.name)
    return MADE


def set_up(ask, account: str, wants: Sequence[Want], say=print) -> str:
    """The whole thing: Allow, make, read back, revoke. Returns MADE, DECLINED,
    NOT_ACCEPTED or FAILED; anything but MADE means "show the hand steps".
    Never raises."""
    grant = None
    try:
        grant = allow(ask, account, say)
        if grant is None:
            return DECLINED
        return make(grant, wants, say)
    except Exception as e:  # noqa: BLE001 -- the hand steps still work
        say("      Lucy couldn't make the filter: %s" % type(e).__name__)
        return FAILED
    finally:
        if grant is not None:
            try:
                grant.revoke()
            except Exception:  # noqa: BLE001
                pass
