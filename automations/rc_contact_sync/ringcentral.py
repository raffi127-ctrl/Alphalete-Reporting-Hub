"""RingCentral side: create the contacts, then check the texts.

ONE IDENTITY DOES BOTH JOBS. We sign in as Taylor
(taylormkmiller7@gmail.com, ext 134 -- Megan 2026-09-02), so the contacts go
into the address book of the line that texts these customers AND her message
store is the one we read. Both calls address extension '~' -- whoever the
token is -- rather than an extension number, which is a thing that gets
reassigned.

CHECK WHO THE TOKEN IS BEFORE WRITING ANYTHING. A JWT from the other
RingCentral account in this business, or from a different user in this one,
authenticates perfectly well and would quietly file every B2B customer in the
wrong address book and read the wrong inbox -- a run that looks completely
successful. assert_identity() is what stops that, and it is not optional.
[[reference_ov_session_identity]]

`watch_jwt` in the creds file stays as an escape hatch for the day the texts
move to a line the contacts don't live on; normally it is absent and the one
token does everything.

Contacts are never created blind: the address book is indexed by phone first,
so a re-run, a same customer buying twice, or a hand-added contact all end in
'already there', not a duplicate.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from automations.shared.name_case import titlecase_name
from automations.rc_contact_sync import config as C


class RCError(RuntimeError):
    pass


def norm_phone(v: str) -> str:
    """Last 10 digits -- the only part two systems agree on. '(214) 845-6450',
    '+12148456450' and '214.845.6450' all normalise to '2148456450'."""
    digits = re.sub(r"\D", "", v or "")
    return digits[-10:] if len(digits) >= 10 else digits


def e164(v: str) -> str:
    d = re.sub(r"\D", "", v or "")
    if len(d) == 10:
        return "+1" + d
    if len(d) == 11 and d.startswith("1"):
        return "+" + d
    return ("+" + d) if d else ""


def split_name(full: str) -> Tuple[str, str]:
    """'MARIA DE LA CRUZ' -> ('Maria', 'De La Cruz'). SaraPlus writes names in
    caps; RingCentral shows them exactly as given, so they are title-cased
    here. [[feedback_report_formatting_standard]]"""
    parts = [p for p in re.split(r"\s+", titlecase_name(full).strip()) if p]
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


# --- auth ---------------------------------------------------------------------

def token(creds: Dict[str, str], jwt: Optional[str] = None) -> str:
    r = requests.post(
        "%s/restapi/oauth/token" % C.RC_BASE_URL,
        auth=(creds["client_id"], creds["client_secret"]),
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
              "assertion": jwt or creds["jwt"]},
        timeout=20)
    if not r.ok:
        raise RCError("RingCentral auth failed (%s): %s"
                      % (r.status_code, r.text[:300]))
    return r.json()["access_token"]


def _get(token: str, path: str, params: Optional[dict] = None) -> dict:
    """GET with the 429 back-off every RingCentral loop needs."""
    hdr = {"Authorization": "Bearer %s" % token}
    url = "%s%s" % (C.RC_BASE_URL, path)
    for _ in range(8):
        r = requests.get(url, headers=hdr, params=params or {}, timeout=25)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 15)))
            continue
        if not r.ok:
            raise RCError("GET %s -> %s: %s" % (path, r.status_code, r.text[:300]))
        return r.json()
    raise RCError("GET %s: rate limited after retries" % path)


def identity(token: str) -> Dict[str, str]:
    """Who this token actually is, and which account."""
    me = _get(token, "/restapi/v1.0/account/~/extension/~")
    contact = me.get("contact", {}) or {}
    return {"extension_id": str(me.get("id", "")),
            "extension_number": str(me.get("extensionNumber", "")),
            "name": ("%s %s" % (contact.get("firstName", ""),
                                contact.get("lastName", ""))).strip(),
            "email": (contact.get("email", "") or "").strip().lower(),
            "account_id": str(me.get("account", {}).get("id", ""))}


def assert_identity(me: Dict[str, str], expected_email: str) -> None:
    """Stop unless the token is the user we meant to be.

    The whole report is 'write into THIS address book, read THIS inbox'. A
    token for the wrong user does both of those things successfully against
    the wrong data, and nothing downstream would ever notice -- so the check
    is a hard stop, not a warning. Set `expected_email` to "" in the creds
    file to deliberately turn it off (e.g. the account's email was changed)."""
    want = (expected_email or "").strip().lower()
    if not want:
        return
    if me.get("email") != want:
        raise RCError(
            "this RingCentral token is %s <%s> (ext %s, account %s), not %s. "
            "Contacts would be written into the wrong address book and the "
            "wrong inbox would be read for the follow-up check -- both of "
            "which would look like a successful run. Mint the JWT on %s, or "
            "set \"expected_email\" in %s if that address really did change."
            % (me.get("name") or "?", me.get("email") or "no email",
               me.get("extension_number") or "?", me.get("account_id") or "?",
               want, want, C.RC_CREDS_PATH))


def extensions(token: str) -> List[dict]:
    return _get(token, "/restapi/v1.0/account/~/extension",
                {"perPage": 200}).get("records", [])


# --- contacts -----------------------------------------------------------------

def address_book(token: str, ext_id: str) -> List[dict]:
    """Every personal contact in that extension's address book."""
    out, page = [], 1
    while True:
        data = _get(token,
                    "/restapi/v1.0/account/~/extension/%s/address-book/contact" % ext_id,
                    {"perPage": 250, "page": page})
        out += data.get("records", [])
        if not data.get("navigation", {}).get("nextPage"):
            break
        page += 1
        time.sleep(0.3)
    return out


def index_by_phone(contacts: List[dict]) -> Dict[str, dict]:
    """{normalised phone -> the contact holding it}. Every phone field is
    indexed, not just mobilePhone: a contact somebody added by hand years ago
    may carry the number as a business or home line, and creating a second
    card for it is exactly the duplicate we are avoiding."""
    idx: Dict[str, dict] = {}
    fields = ("mobilePhone", "homePhone", "homePhone2", "businessPhone",
              "businessPhone2", "otherPhone", "businessPhone3", "callbackPhone")
    for c in contacts:
        for f in fields:
            n = norm_phone(c.get(f, "") or "")
            if n:
                idx.setdefault(n, c)
    return idx


def create_contact(token: str, ext_id: str, *, first: str, last: str,
                   company: str, phone: str, notes: str) -> dict:
    """One personal contact, laid out the way Carlos fills the form by hand:
    business name in Company, the number as Mobile, 'Rep Name: X' in Notes."""
    body = {"firstName": first or company or "Customer",
            "lastName": last,
            "company": company,
            "mobilePhone": e164(phone),
            "notes": notes}
    hdr = {"Authorization": "Bearer %s" % token,
           "Content-Type": "application/json"}
    url = ("%s/restapi/v1.0/account/~/extension/%s/address-book/contact"
           % (C.RC_BASE_URL, ext_id))
    for _ in range(5):
        r = requests.post(url, headers=hdr, json=body, timeout=25)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 15)))
            continue
        if not r.ok:
            raise RCError("creating contact %r failed (%s): %s"
                          % (company or first, r.status_code, r.text[:300]))
        return r.json()
    raise RCError("creating contact %r: rate limited after retries" % company)


# --- messages -----------------------------------------------------------------

def sms_for_day(token: str, ext_id: str, day: dt.date) -> List[dict]:
    """Every SMS in that extension's store for ONE local day.

    The window is sent as UTC instants around the day's local bounds and then
    re-filtered locally, because a text at 6pm Central is 'tomorrow' in UTC
    and would otherwise be counted against the wrong day."""
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    end = start + dt.timedelta(days=1)
    params = {"messageType": "SMS", "perPage": 250,
              "dateFrom": start.astimezone(dt.timezone.utc)
                               .strftime("%Y-%m-%dT%H:%M:%SZ"),
              "dateTo": end.astimezone(dt.timezone.utc)
                           .strftime("%Y-%m-%dT%H:%M:%SZ")}
    out, page = [], 1
    while True:
        params["page"] = page
        try:
            data = _get(token,
                        "/restapi/v1.0/account/~/extension/%s/message-store" % ext_id,
                        params)
        except RCError as e:
            if "403" in str(e) or "401" in str(e):
                raise RCError(
                    "this RingCentral token cannot read extension %s's "
                    "messages (%s). The token signs in as %s and normally "
                    "reads its OWN store ('~'), so this means the app is "
                    "missing the Read Messages scope, or watch_extension_id "
                    "was pointed at somebody else's line -- a JWT "
                    "authenticates one user, and reading another line needs a "
                    "`watch_jwt` minted on that user. Raised rather than "
                    "returning nothing: no messages reads as 'nobody texted "
                    "any of them', which would chase every rep."
                    % (ext_id, str(e)[:120], C.RC_LOGIN_EMAIL))
            raise
        out += data.get("records", [])
        if not data.get("navigation", {}).get("nextPage"):
            break
        page += 1
        time.sleep(0.3)
    return out


def _msg_numbers(m: dict) -> List[str]:
    nums = [norm_phone(m.get("from", {}).get("phoneNumber", ""))]
    for t in (m.get("to") or []):
        nums.append(norm_phone(t.get("phoneNumber", "")))
    return [n for n in nums if n]


def texted(messages: List[dict], phone: str, names: List[str]) -> bool:
    """Was this customer texted on that line?

    Carlos's rule, in his words: 'see if there was a text message received
    with that customer's phone number, name, or business name.' Phone is the
    real test; the name/business text search is the backstop for a customer
    who was messaged from a second number or whose number was typed in
    differently. A name needs 4+ characters to count, so an initial or a
    two-letter business never matches half the day's traffic."""
    want = norm_phone(phone)
    if want:
        for m in messages:
            if want in _msg_numbers(m):
                return True
    needles = [n.lower() for n in names if n and len(n.strip()) >= 4]
    if needles:
        for m in messages:
            body = (m.get("subject", "") or "").lower()
            if body and any(n in body for n in needles):
                return True
    return False
