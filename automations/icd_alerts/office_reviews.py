"""This office's Google reviews, read and answered from THIS computer with the
owner's OWN Google sign-in (Megan 2026-11-15: "the goal [is] for everything to
move over to the relay machine so we can offer EVERYTHING to each ICD").

Lucy 3 still writes the replies and runs the Slack approvals (that needs
Alphalete's Claude + Slack keys, which never live on an office computer).
This computer only:
  google_signin  -- the owner signs Lucy into THEIR Google once (a window, like
                    Zoho's). The token stays on this computer.
  google_reviews -- the reviews on their listing that have no reply yet.
  google_reply   -- post one approved reply.

They ride the two job kinds the relay already knows (social_check = read,
social_post = publish), told apart by payload["do"], so the relay itself
needs no change.

Standard library only: an office computer has patchright + certifi, nothing
else, and must not need an install for this.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Dict, List, Optional

from automations.icd_alerts import config as C

TOKEN_PATH = C.APP_DIR / "google-reviews-token.json"
SCOPE = "https://www.googleapis.com/auth/business.manage"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
V4 = "https://mybusiness.googleapis.com/v4"
ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
SIGNIN_MAX_MINUTES = 14          # inside the scheduled run's 20-minute hard stop
READ_MAX = 25                    # reviews per answer: one relay cell holds ~50k chars


# ---- HTTP (urllib only) --------------------------------------------------------
def _req(method: str, url: str, *, data: Optional[Dict] = None, form: Optional[Dict] = None,
         token: str = "") -> Dict:
    body, headers = None, {}
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        import ssl
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            raw = r.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            msg = json.loads(raw).get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except ValueError:
            msg = raw[:200]
        raise RuntimeError("Google %s: %s" % (e.code, msg))
    return json.loads(raw)


# ---- the owner's token --------------------------------------------------------------
def _load() -> Dict:
    try:
        return json.loads(TOKEN_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _access_token() -> str:
    t = _load()
    if not t.get("refresh_token"):
        raise RuntimeError("signed_out")
    if t.get("access_token") and t.get("expires_at", 0) > time.time() + 60:
        return t["access_token"]
    r = _req("POST", TOKEN, form={"client_id": t["client_id"], "client_secret": t["client_secret"],
                                  "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    t.update(access_token=r["access_token"], expires_at=time.time() + int(r.get("expires_in", 3600)))
    TOKEN_PATH.write_text(json.dumps(t))
    return t["access_token"]


def signin(payload: Dict, log=print) -> Dict:
    """Open Google's sign-in on this screen (the owner's own account), catch
    the answer on this computer, keep the token here. Never sees a password."""
    cid, secret = payload.get("client_id"), payload.get("client_secret")
    if not cid or not secret:
        return {"status": "error", "error": "job had no Google app details"}
    minutes = min(int(payload.get("minutes") or SIGNIN_MAX_MINUTES), SIGNIN_MAX_MINUTES)
    state, got = secrets.token_urlsafe(16), {}

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if q.get("state") == state:
                got.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = ("All set. Lucy can answer your Google reviews now. You can close this tab."
                   if q.get("code") else "That didn't go through. Lucy will ask again.")
            self.wfile.write(("<h2 style='font-family:Arial'>%s</h2>" % msg).encode())

        def log_message(self, *a):  # quiet
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    redirect = "http://127.0.0.1:%d/" % port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    log("google: opening Google for the owner to sign in (%d min)" % minutes)
    webbrowser.open(url)                       # a PERSON acts here (visible_windows.py)
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline and not got:
            time.sleep(1)
    finally:
        srv.shutdown()
    if not got.get("code"):
        return {"status": "timed_out" if not got else "refused", "error": got.get("error", "")}
    r = _req("POST", TOKEN, form={"code": got["code"], "client_id": cid, "client_secret": secret,
                                  "redirect_uri": redirect, "grant_type": "authorization_code"})
    if not r.get("refresh_token"):
        return {"status": "error", "error": "Google gave no lasting sign-in (try again)"}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "client_id": cid, "client_secret": secret, "refresh_token": r["refresh_token"],
        "access_token": r.get("access_token", ""), "expires_at": time.time() + int(r.get("expires_in", 3600))}))
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    return {"status": "signed_in", "listings": listings()}


def listings() -> List[Dict]:
    """Every Google listing the signed-in owner manages: [{path, title}]."""
    tok = _access_token()
    out = []
    for acct in _req("GET", ACCOUNTS + "/accounts", token=tok).get("accounts") or []:
        r = _req("GET", "%s/%s/locations?readMask=name,title&pageSize=100" % (INFO, acct["name"]), token=tok)
        for loc in r.get("locations") or []:
            out.append({"path": "%s/%s" % (acct["name"], loc["name"]), "title": loc.get("title", "")})
    return out


# ---- read + reply ---------------------------------------------------------------------
_STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def unanswered(location: str, skip: List[str] = ()) -> Dict:
    """Reviews on `location` with no business reply yet (newest first), minus
    the ones Lucy 3 already has in hand (`skip`), at most READ_MAX."""
    tok = _access_token()
    skip, out, page, seen = set(skip or ()), [], "", 0
    while True:
        url = "%s/%s/reviews?pageSize=50%s" % (V4, location, "&pageToken=" + page if page else "")
        r = _req("GET", url, token=tok)
        for rv in r.get("reviews") or []:
            seen += 1
            if rv.get("reviewReply") or rv["name"] in skip:
                continue
            out.append({"name": rv["name"], "rating": _STARS.get(rv.get("starRating", ""), None),
                        "text": (rv.get("comment") or "")[:2000],
                        "author": (rv.get("reviewer") or {}).get("displayName", ""),
                        "time": rv.get("createTime", "")})
            if len(out) >= READ_MAX:
                return {"status": "ok", "reviews": out, "total": r.get("totalReviewCount"), "more": True}
        page = r.get("nextPageToken") or ""
        if not page:
            return {"status": "ok", "reviews": out, "total": r.get("totalReviewCount", seen), "more": False}


def reply(name: str, comment: str) -> Dict:
    _req("PUT", "%s/%s/reply" % (V4, name), data={"comment": comment}, token=_access_token())
    return {"status": "replied", "name": name}


# ---- job entry points (social_post.check / social_post.post hand these over) ----------
def read_job(payload: Dict, log=print) -> Dict:
    try:
        return unanswered(str(payload.get("location") or ""), payload.get("skip") or [])
    except RuntimeError as e:
        return {"status": "signed_out" if str(e) == "signed_out" else "error", "error": str(e)[:200]}


def reply_job(payload: Dict, live: bool, log=print) -> Dict:
    name, comment = str(payload.get("name") or ""), str(payload.get("comment") or "").strip()
    if not name or not comment:
        return {"status": "error", "error": "job had no review or no reply"}
    if not live:
        return {"status": "dry_run", "would_reply": name}
    try:
        return reply(name, comment)
    except RuntimeError as e:
        return {"status": "signed_out" if str(e) == "signed_out" else "error", "error": str(e)[:200],
                "name": name}
