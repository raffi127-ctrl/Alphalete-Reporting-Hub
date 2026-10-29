"""Can this Mac read the owner's SaraPlus code TEXTS? A check, nothing more.

WHY (Eve, 2026-10-29). Eveliz's SaraPlus codes come by SMS, not mail, so the
mail forward sara_code.py waits on can never answer for her. The other way in
is her iPhone's Text Message Forwarding: the texts then land in Messages on
her iMac, where Lucy can read them. That needs three things, and this files
which of them her Mac has, once a day, without asking her anything:

    can read   -- this process may open ~/Library/Messages/chat.db
                  (no: Lucy needs Full Disk Access)
    signed in  -- Messages on this Mac has any recent messages at all
                  (no: the iMac is not on her Apple ID)
    forwarding -- texts (service SMS) arrive here, and any from SaraPlus
                  (no SMS: Text Message Forwarding is off for this Mac)

READ-ONLY, AND ONLY COUNTS LEAVE THE MAC. The connection is mode=ro. What
travels is how many messages, of which service, and when -- never a message's
words, never a phone number. The one handle sent is SaraPlus's own sender,
and only when it is a short code (a business number, not a person), because
reading the code later needs it.

Filed as a `probe-messages` fault: kept in the Faults tab, never posted
(see post.notify_faults).

    python -m automations.icd_alerts.messages_probe --check    # run it now
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
from typing import Dict, List, Optional

from automations.icd_alerts import config as C

# Offices whose SaraPlus codes come by text. Eveliz first (Eve 2026-10-29).
PROBE_KEYS = frozenset({"eveliz"})

STAGE = "probe-messages"
DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH = 978307200
RECENT_DAYS = 14
SARA_DAYS = 30
# Matched against the message's own text, on the Mac; the text never leaves.
SARA_WORDS = ("saraplus", "sara plus", "sara+")
CHECK_EVERY_HOURS = 24
_STATE = C.APP_DIR / "messages-probe.json"


def _apple_time(v) -> Optional[dt.datetime]:
    """message.date: nanoseconds since 2001 on current macOS, seconds before."""
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 10 ** 12:
        v //= 10 ** 9
    return dt.datetime.fromtimestamp(v + APPLE_EPOCH)


def _apple_value(when: dt.datetime) -> int:
    """`when` as message.date compares it on current macOS (nanoseconds)."""
    return int((when.timestamp() - APPLE_EPOCH) * 10 ** 9)


def _body(text, blob) -> str:
    """The words of one message, for matching only. Newer macOS leaves `text`
    empty and keeps them in attributedBody."""
    if text:
        return str(text)
    if isinstance(blob, (bytes, bytearray)):
        return bytes(blob).decode("utf-8", "replace")
    return ""


def _short_code(handle: str) -> bool:
    digits = "".join(ch for ch in handle or "" if ch.isdigit())
    return bool(digits) and digits == (handle or "").strip() and len(digits) <= 6


def look(now: Optional[dt.datetime] = None, db: str = DB) -> Dict:
    """What this Mac's Messages shows. Never raises."""
    now = now or dt.datetime.now()
    out: Dict = {"can_read": False, "why": "", "recent": {}, "last": None,
                 "sara": 0, "sara_last": None, "sara_from": []}
    if not os.path.exists(db):
        out["why"] = "no Messages database (Messages never opened on this Mac?)"
        return out
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
    except sqlite3.Error as e:
        out["why"] = str(e).split("\n")[0][:120]
        return out
    try:
        try:
            con.execute("SELECT COUNT(*) FROM message LIMIT 1").fetchone()
        except sqlite3.Error as e:
            out["why"] = ("%s -- no Full Disk Access"
                          % str(e).split("\n")[0][:120])
            return out
        out["can_read"] = True
        since = _apple_value(now - dt.timedelta(days=RECENT_DAYS))
        for service, n, last in con.execute(
                """SELECT COALESCE(m.service, '?'), COUNT(*), MAX(m.date)
                     FROM message m
                    WHERE m.is_from_me = 0 AND m.date > ?
                    GROUP BY 1""", (since,)).fetchall():
            out["recent"][service] = n
            t = _apple_time(last)
            if t and (out["last"] is None or t > out["last"]):
                out["last"] = t
        since = _apple_value(now - dt.timedelta(days=SARA_DAYS))
        rows = con.execute(
            """SELECT m.date, m.text, m.attributedBody, COALESCE(h.id, '')
                 FROM message m
                 LEFT JOIN handle h ON h.ROWID = m.handle_id
                WHERE m.is_from_me = 0 AND m.date > ?
                  AND COALESCE(m.service, '') = 'SMS'
                ORDER BY m.date DESC LIMIT 3000""", (since,)).fetchall()
        for when, text, blob, handle in rows:
            if not any(w in _body(text, blob).lower() for w in SARA_WORDS):
                continue
            out["sara"] += 1
            t = _apple_time(when)
            if t and (out["sara_last"] is None or t > out["sara_last"]):
                out["sara_last"] = t
            if _short_code(handle) and handle not in out["sara_from"]:
                out["sara_from"].append(handle)
    except sqlite3.Error as e:
        out["why"] = "read failed: %s" % str(e).split("\n")[0][:120]
    finally:
        con.close()
    return out


def verdict(seen: Dict) -> List[str]:
    """One line per requirement, in the order the owner would fix them."""
    if not seen["can_read"]:
        return ["can read: NO -- %s" % (seen["why"] or "?"),
                "signed in: ? (cannot tell until Lucy can read)",
                "forwarding: ? (cannot tell until Lucy can read)"]
    total = sum(seen["recent"].values())
    sms = seen["recent"].get("SMS", 0)
    out = ["can read: yes"]
    out.append("signed in: %s" % (
        "yes (%d messages in %dd)" % (total, RECENT_DAYS) if total
        else "NO -- no messages here in %dd" % RECENT_DAYS))
    if seen["sara"]:
        out.append("forwarding: yes -- %d SaraPlus text(s) in %dd, last %s"
                   % (seen["sara"], SARA_DAYS,
                      seen["sara_last"].strftime("%Y-%m-%d %H:%M")
                      if seen["sara_last"] else "?"))
    elif sms:
        out.append("forwarding: texts arrive (%d SMS in %dd) but none from "
                   "SaraPlus in %dd" % (sms, RECENT_DAYS, SARA_DAYS))
    else:
        out.append("forwarding: NO -- no texts (SMS) here in %dd" % RECENT_DAYS)
    return out


def _load() -> Dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: Dict) -> None:
    try:
        C.app_dir()
        _STATE.write_text(json.dumps(s), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- only costs another check
        pass


def wanted(rec: Dict) -> bool:
    return str(rec.get("office_key") or "").strip().lower() in PROBE_KEYS


def check_due(state: Dict, now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    try:
        last = dt.datetime.fromisoformat(state.get("last", ""))
    except (TypeError, ValueError):
        return True
    return now - last >= dt.timedelta(hours=CHECK_EVERY_HOURS)


def run_check(log=print) -> int:
    """File one probe per office here that asked. Never raises."""
    from automations.icd_alerts import relay as R
    filed = 0
    now = dt.datetime.now()
    try:
        seen = look(now)
        lines = verdict(seen)
    except Exception as e:  # noqa: BLE001
        seen, lines = {}, ["probe failed: %s" % type(e).__name__]
    detail = "\n".join(lines + [
        "recent by service: %s" % (json.dumps(seen.get("recent") or {})),
        "last message: %s" % (seen["last"].isoformat(timespec="minutes")
                              if seen.get("last") else "none"),
        "saraplus sender: %s" % (", ".join(seen.get("sara_from") or []) or "?"),
        "mac user: %s" % (os.environ.get("USER") or "?")])
    short = " | ".join(l.split(" -- ")[0] for l in lines)
    for rec in C.active_enrollments():
        if not wanted(rec):
            continue
        # STAMPED: the relay folds same-summary rows and keeps the FIRST detail.
        if R.report_fault(STAGE, "Messages check %s: %s"
                          % (now.strftime("%m/%d %H:%M"), short),
                          detail=detail, log=None,
                          office_key=rec.get("office_key", "")):
            filed += 1
    _save({"last": now.isoformat(timespec="seconds")})
    if log:
        log("messages check: %s" % short)
    return filed


def maybe_run(log=print) -> bool:
    """Called from every agent tick. Free unless this office is in PROBE_KEYS
    and a day has passed since the last check."""
    if sys.platform != "darwin" or os.environ.get("LUCY_NO_MESSAGES_PROBE"):
        return False
    if not any(wanted(r) for r in C.active_enrollments()):
        return False
    if not check_due(_load()):
        return False
    run_check(log=log)
    return True


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="run the check now")
    a = ap.parse_args(argv)
    if a.check:
        for l in verdict(look()):
            print(l)
        print("filed %d check(s)" % run_check(log=None))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
