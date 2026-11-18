"""Send SMS from Dylan's line and read inbound replies — via the dedicated
feedback JWT (the "Dylan Twaddle" ext that owns 214-845-6450, so sends go out
same-extension). Thin wrappers over the RingCentral message-store API.

RingCentral rate-limits the OAuth token endpoint hard, so a run authenticates
ONCE (get_access_token, with backoff) and reuses that token for every send —
never one token fetch per message, which 429s after a handful (2026-11-18).
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Dict, List, Optional, Tuple

import requests

from automations.rc_contact_sync import ringcentral as RC
from automations.cancel_feedback import config as C
from automations.cancel_feedback.source import normalize_phone


def get_access_token(creds: Dict[str, str], *, retries: int = 6, log=print) -> str:
    """ONE access token for a whole run, asserting it's the extension that owns
    the sending number and has SMS scope. Backs off through the token-endpoint
    rate limit instead of dying on the first 429."""
    last = None
    for i in range(retries):
        try:
            info = RC.token_info(creds)
            owner = str(info.get("owner_id", ""))
            want = str(creds.get("expected_owner_id", ""))
            if want and owner != want:
                raise RuntimeError("feedback JWT is extension %s, expected %s "
                                   "(wrong RingCentral user?)" % (owner, want))
            if "SMS" not in (info.get("scope", "") or "").split():
                raise RuntimeError("feedback JWT has no SMS scope: %r"
                                   % info.get("scope"))
            return info["access_token"]
        except Exception as e:                             # noqa: BLE001
            last = e
            wait = 15 * (i + 1)
            log("  token fetch attempt %d failed (%s) — waiting %ds"
                % (i + 1, str(e).splitlines()[0][:90], wait))
            time.sleep(wait)
    raise RuntimeError("could not get a RingCentral token after %d tries: %s"
                       % (retries, last))


def send(token: str, send_from: str, to: str, text: str,
         *, log=print) -> Tuple[bool, Optional[str], Optional[dict]]:
    """Send one SMS with an already-fetched token. (ok, message_id, error)."""
    r = requests.post(
        C.RC_BASE_URL + "/restapi/v1.0/account/~/extension/~/sms",
        headers={"Authorization": "Bearer %s" % token},
        json={"from": {"phoneNumber": send_from},
              "to": [{"phoneNumber": to}], "text": text}, timeout=30)
    if r.status_code in (200, 201):
        return True, str(r.json().get("id") or ""), None
    try:
        err = r.json()
    except Exception:                                      # noqa: BLE001
        err = {"status": r.status_code, "body": r.text[:200]}
    log("  ✗ send to %s failed: HTTP %s %s"
        % (to, r.status_code, str(err)[:160]))
    return False, None, err


def send_sms(creds: Dict[str, str], to: str, text: str,
             *, log=print) -> Tuple[bool, Optional[str], Optional[dict]]:
    """Convenience one-shot (fetches its own token). For bulk sends use
    get_access_token once + send() per message instead."""
    return send(get_access_token(creds, log=log), creds["send_from"], to, text, log=log)


def replies_since(creds: Dict[str, str], since: dt.date,
                  *, log=print) -> List[dict]:
    """All inbound SMS on the line since `since` (date, inclusive), newest
    last. Each: {phone (+1...), text, time, id}. phone is normalized so it
    matches the stored outreach keys."""
    tok = get_access_token(creds, log=log)
    hdr = {"Authorization": "Bearer %s" % tok}
    url = C.RC_BASE_URL + "/restapi/v1.0/account/~/extension/~/message-store"
    params = {"messageType": "SMS", "direction": "Inbound",
              "dateFrom": since.isoformat() + "T00:00:00.000Z", "perPage": 1000}
    out: List[dict] = []
    while url:
        r = requests.get(url, headers=hdr, params=params, timeout=30)
        if r.status_code != 200:
            log("  ✗ reading replies failed: HTTP %s %s"
                % (r.status_code, r.text[:160]))
            break
        j = r.json()
        for m in j.get("records", []):
            phone = normalize_phone(m.get("from", {}).get("phoneNumber", ""))
            if not phone:
                continue
            out.append({"phone": phone, "text": (m.get("subject") or "").strip(),
                        "time": m.get("creationTime", ""), "id": str(m.get("id") or "")})
        nxt = (j.get("navigation", {}).get("nextPage", {}) or {}).get("uri")
        url, params = (nxt, None) if nxt else (None, None)
    out.sort(key=lambda x: x["time"])
    return out


def is_opt_out(text: str) -> bool:
    """True if the reply is a STOP-style keyword (first word)."""
    first = (text or "").strip().lower().split()
    return bool(first) and first[0].strip(".!") in C.STOP_WORDS
