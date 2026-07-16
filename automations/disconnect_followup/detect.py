"""RingCentral response detection. For each customer phone, find Dylan's
outbound feedback inquiry and, once the customer has replied, return the whole
conversation (both sides) after it. Reuses the rc_autoread creds/auth."""
from __future__ import annotations

import datetime as dt
import time
from typing import Dict, List, Optional, Tuple

import requests

from automations.rc_autoread import run as _rc
from .pull import norm_phone

# Distinctive phrase common to both inquiry variants ("...order was cancelled"
# and "...was disconnected"). Identifies an outbound inquiry.
ANCHOR = "gathering feedback on how to improve in the market"


def _body(m: dict) -> str:
    return (m.get("subject", "") or "").strip()


def _from(m: dict) -> str:
    return m.get("from", {}).get("phoneNumber", "")


def _fetch_recent(token: str, days: int, logfn) -> List[dict]:
    """All SMS in the extension's store within the window, with 429 backoff."""
    hdr = {"Authorization": f"Bearer {token}"}
    url = (f"{_rc.BASE_URL}/restapi/v1.0/account/~/extension/"
           f"{_rc.EXTENSION_ID}/message-store")
    since = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recs, page = [], 1
    while True:
        for _ in range(8):
            r = requests.get(url, headers=hdr, params={
                "messageType": "SMS", "dateFrom": since,
                "perPage": 100, "page": page}, timeout=20)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                logfn(f"  rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            break
        else:
            raise RuntimeError("RingCentral rate limited after retries")
        recs += data.get("records", [])
        if not data.get("navigation", {}).get("nextPage"):
            break
        page += 1
        time.sleep(0.4)
    return recs


def _fmt(m: dict) -> str:
    who = "Dylan" if _from(m) == _rc.MY_NUMBER else "Customer"
    ts = m.get("creationTime", "")[5:16].replace("T", " ")
    return f"[{ts}] {who}: {_body(m)}"


def build_index(token: str, days: int, logfn=print) -> Dict[str, List[dict]]:
    """messages grouped by the customer's normalized phone."""
    by_phone: Dict[str, List[dict]] = {}
    for m in _fetch_recent(token, days, logfn):
        cust = ((m.get("to") or [{}])[0].get("phoneNumber", "")
                if _from(m) == _rc.MY_NUMBER else _from(m))
        by_phone.setdefault(norm_phone(cust), []).append(m)
    return by_phone


def all_responses(token: str, days: int, logfn=print) -> Dict[str, Tuple[str, str]]:
    """Every phone whose customer has replied to the inquiry -> (thread, date)."""
    by_phone = build_index(token, days, logfn)
    out: Dict[str, Tuple[str, str]] = {}
    for phone in by_phone:
        if not phone:
            continue
        thread, date = conversation_for(phone, by_phone)
        if thread:                       # customer actually replied
            out[phone] = (thread, date)
    return out


def conversation_for(phone: str, by_phone: Dict[str, List[dict]]
                     ) -> Tuple[Optional[str], str]:
    """Return (thread, latest_reply_date) for a phone.
      - (None, "")  -> no inquiry was sent to this phone.
      - ("", "")    -> inquiry sent but the customer hasn't replied yet.
      - (thread, d) -> customer replied; thread = the conversation AFTER the
                       inquiry (both sides), NOT including the inquiry itself.
    """
    msgs = sorted(by_phone.get(phone, []), key=lambda m: m.get("creationTime", ""))
    inq = next((m for m in msgs if _from(m) == _rc.MY_NUMBER
                and ANCHOR in _body(m).lower()), None)
    if not inq:
        return None, ""
    it = inq.get("creationTime", "")
    after = [m for m in msgs if m.get("creationTime", "") > it and _body(m)]
    customer_replies = [m for m in after if _from(m) != _rc.MY_NUMBER]
    if not customer_replies:
        return "", ""   # inquiry sent, customer hasn't responded yet -> stays blank
    # Customer has responded: log the WHOLE conversation that follows the initial
    # inquiry — both sides (customer replies + Dylan's follow-ups) — but NOT the
    # initial inquiry message itself.
    thread = "\n".join(_fmt(m) for m in after)
    latest = customer_replies[-1].get("creationTime", "")[:10]
    return thread, latest
