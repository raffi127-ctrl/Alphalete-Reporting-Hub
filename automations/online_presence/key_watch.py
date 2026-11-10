"""Tell someone when Lucy can't read Google reviews -- never fail quietly again.

Megan 2026-11-10: "i also never got alerted that the key was missing - that
should be built out". From 8/22 to 11/09 Lucy 3 had no Google review key. The
noon reply run quietly fell back to Google's 5-review sample, exited clean, and
the bad-review check logged "review_read_failed" to a file nobody reads. Andrea's
review sat unanswered for seven weeks.

Rides the 10-minute LucyECO Social pass (run.py). One Google login covers
Alphalete AND every office, so one check covers them all:

  * key missing / expired / refused by Google -> alert right away
  * anything else (a network blip)           -> alert after 3 passes in a row
  * still broken                             -> remind once a day, never every pass
  * working again                            -> one "it's back" note

Where: a short header in the alerts channel with the detail + the fix in its
thread, and a DM to the LucyECO Social manager (rooms.MANAGER).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STATE = Path.home() / ".config" / "brand-audit" / "gbp_key_watch.json"
BLIP_PASSES = 3                  # a non-key error has to repeat before it alerts
URGENT = ("missing", "expired", "refused")


def _load() -> Dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d: Dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=2))


def _machine() -> str:
    try:
        name = (Path(__file__).resolve().parents[2] / ".machine-profile").read_text().strip()
        if name:
            return name
    except Exception:
        pass
    import socket
    return socket.gethostname()


def probe(location: str) -> Optional[Tuple[str, str]]:
    """None when the key works; else (kind, plain-words reason)."""
    from automations.brand_audit import gbp_api
    if not gbp_api.has_token():
        return "missing", "Google's review key isn't on this computer"
    try:
        gbp_api.list_reviews(location, limit=1)
        return None
    except gbp_api.GBPAccessError:
        return "refused", "Google refused the review key (access denied)"
    except Exception as e:
        msg = str(e)
        if "invalid" in msg.lower() or "refresh" in msg.lower() or "invalid_grant" in msg:
            return "expired", "Google's review key has expired or was revoked"
        return "error", f"Google's review API isn't answering ({type(e).__name__})"


def messages(kind: str, why: str, machine: str, since: str) -> Tuple[str, str]:
    head = ":key: *Lucy can't read Google reviews*"
    fix = (f"Paste to Claude: \"Put the Google review key back on {machine}\" "
           "(the laptop's working key goes over with set_gbp_token)."
           if kind == "missing" else
           "Paste to Claude: \"Re-authorize Google reviews and put the new key on "
           f"{machine}\" (gbp_api --authorize on the laptop, then set_gbp_token)."
           if kind in ("expired", "refused") else
           "Usually Google having a bad hour. If this is still here tomorrow, "
           "paste it to Claude.")
    detail = "\n".join([
        f"*What's wrong:* {why} ({machine}).",
        "*What stops:* review replies and bad-review alerts for Alphalete and "
        "every LucyECO Social office.",
        f"*Since:* {since}",
        f"*Fix:* {fix}",
    ])
    return head, detail


def check(*, live: bool, cl=None, location: str | None = None,
          now: dt.datetime | None = None) -> List[Dict]:
    from automations.online_presence import offices, rooms
    now = now or dt.datetime.now()
    loc = location if location is not None else offices.alphalete().gbp_location
    bad = probe(loc)
    st = _load()
    if bad is None:
        out = [{"action": "ok"}]
        if st.get("alerted") and live:
            if cl is None:
                from automations.brand_audit.social_inbox import _client
                cl = _client()
            back = (":white_check_mark: *Google reviews are working again* "
                    f"(down since {st.get('down_since')}). Replies and bad-review "
                    "alerts pick back up on their own.")
            cl.chat_postMessage(channel=rooms.SOCIAL_ALERTS, text=back)
            cl.chat_postMessage(channel=rooms.MANAGER, text=back)
            out = [{"action": "recovered"}]
        if live and st:
            _save({})
        return out
    kind, why = bad
    st["fails"] = int(st.get("fails") or 0) + 1
    st.setdefault("down_since", now.strftime("%b %d %I:%M %p"))
    st["kind"] = kind
    today = now.date().isoformat()
    if kind not in URGENT and st["fails"] < BLIP_PASSES:
        if live:
            _save(st)
        return [{"action": "watching", "kind": kind, "fails": st["fails"]}]
    if st.get("last_alert") == today:
        if live:
            _save(st)
        return [{"action": "still_down", "kind": kind}]
    head, detail = messages(kind, why, _machine(), st["down_since"])
    out = [{"action": "alert" if live else "would_alert", "kind": kind, "why": why}]
    if live:
        if cl is None:
            from automations.brand_audit.social_inbox import _client
            cl = _client()
        r = cl.chat_postMessage(channel=rooms.SOCIAL_ALERTS, text=head)
        cl.chat_postMessage(channel=rooms.SOCIAL_ALERTS, thread_ts=r.get("ts"), text=detail)
        cl.chat_postMessage(channel=rooms.MANAGER, text=f"{head}\n{detail}")
        st["last_alert"], st["alerted"] = today, True
        _save(st)
    return out
