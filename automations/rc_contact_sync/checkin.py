"""Activation texts -- from Taylor's line, ONE-TO-ONE to the customer's main
number, by days since the customer's first activation: "recently activated"
at 0-13 days, "just checking in" at 14-30 days, nothing after 30 (KINDS).

Carlos 2026-11-21: "anyone thats been active for two weeks i want you to
send them a message saying Hey X, this is taylor with ATT. Just checking in
if everything is okay or if you need anything? send this only to the main
line and not in a group message. If they've been active for over 30 days
don't send anything. If they name is a spanish name send it in spanish."

WHO GETS IT (all off the "NDS Order Log" tab on the Vantura Master, the
merged truth Carlos reads; columns resolved by header):
  * at least one of the customer's lines has Line Status "Active";
  * the customer's FIRST activation (earliest Activation Date across every
    line and order they have on the tab) is in the kind's window --
    a customer who has been with us over 30 days gets nothing, even when a
    newer order of theirs activated last week;
  * no line of theirs is marked "Not saveable" in Being worked on;
  * never sent this kind before (its own state file, one entry per customer).
One text per CUSTOMER (deduped by name), not per order or per line.

THE NUMBER: the customer's main contact phone -- the order header's contact
phone in today's wireless feed (Wireless Order # then DSI #), else the main
contact in Taylor's book whose name is exactly the customer's (the sync's
"<Name> - Line N" contacts are never used). Neither -> SKIPPED and logged.
Only that one number goes in `to`, so it is a plain 1:1 SMS, no rep.

LANGUAGE: spanish.language(customer) picks KINDS[kind]['es'] or ['en'].

SAFETY RAILS: DRY RUN by default (prints every recipient and uploads the
plan to the control sheet's 'Checkin Preview' tab); --live sends. State is
saved after each send, so a crash halfway never re-texts anyone.

    python -m automations.rc_contact_sync.checkin              # dry run
    lucy rerun rc_checkin_text                                 # dry run on Lucy 2
    lucy rerun rc_checkin_text --live                          # sends both kinds
    lucy rerun rc_checkin_text --kind recent --live            # one kind only
Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from typing import Dict, List, Optional, Sequence

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.shared.name_case import titlecase_name
from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC
from automations.rc_contact_sync.delivered import _cell, _hdr, _parse_date

REPORT_ID = "rc_checkin_text"
NOT_SAVEABLE = "not saveable"

# Two kinds, by days since the customer's FIRST activation. Each has its own
# once-ever state file, so a customer texted "recent" at day 5 still gets the
# check-in once they reach day 14.
#   recent  -- Carlos 2026-11-21, minutes after the check-in ask: "If they've
#              activated in the last 13 days send them a message saying. Hey X,
#              i seen you recently activated your ATT lines. If you need
#              anything let me know 🙂" (same main-line-only, Spanish rules)
#   checkin -- "active for two weeks" .. "over 30 days don't send anything"
KINDS = {
    "recent": {
        "min": 0, "max": 13, "sent": C.CONFIG_DIR / "rc-recent-sent.json",
        "en": "Hey {first}, I saw you recently activated your AT&T lines. If you need anything let me know \U0001F642",
        "es": "Hola {first}, vi que activó recientemente sus líneas de AT&T. Si necesita algo, avíseme \U0001F642",
    },
    "checkin": {
        "min": 14, "max": 30, "sent": C.CONFIG_DIR / "rc-checkin-sent.json",
        "en": "Hey {first}, this is Taylor with AT&T. Just checking in if everything is okay or if you need anything?",
        "es": "Hola {first}, soy Taylor de AT&T. Solo quería saber si todo está bien o si necesita algo.",
    },
}

# Carlos 2026-11-27 (the three that run now; the two above stay for reference):
#   "anyone that's already received their phones and it's been more than 7
#    days, let's text saying, 'Hey there, do you need any help activating?'"
#   "anyone that's been active for 7 days at least ... 'Hey there, just
#    checking in. Has everything been good with your service? Do you need help
#    with anything?' And if they've been active for 21 days or more, let's send
#    them the same text message."
#   "read through the notes, the text chains, and see if there's anything there
#    that leads you to believe that we shouldn't be texting them" -- the notes
#    rule is DO_NOT_TEXT below; the chains are read by a person (--review).
_CHECK_EN = ("Hey there, just checking in. Has everything been good with your service? "
             "Do you need help with anything?")
_CHECK_ES = ("Hola, solo quería saber cómo va todo. ¿Ha estado bien su servicio? "
             "¿Necesita ayuda con algo?")
KINDS.update({
    "help_activate": {
        "basis": "delivered", "min": 8, "max": None,
        "sent": C.CONFIG_DIR / "rc-help-activate-sent.json",
        "en": "Hey there, do you need any help activating?",
        "es": "Hola, ¿necesita ayuda para activar su servicio?",
    },
    "active7": {
        "min": 7, "max": 20, "sent": C.CONFIG_DIR / "rc-active7-sent.json",
        "en": _CHECK_EN, "es": _CHECK_ES,
    },
    "active21": {
        "min": 21, "max": None, "sent": C.CONFIG_DIR / "rc-active21-sent.json",
        "en": _CHECK_EN, "es": _CHECK_ES,
    },
})
DEFAULT_KINDS = ("help_activate", "active7", "active21")

# A line whose Notes / Taylor's Notes say any of these keeps the WHOLE customer
# off every text here. Claude writes "DO NOT TEXT -- <why>" after reading a
# chain that says the customer is not activating / asked us to stop.
DO_NOT_TEXT = ("do not text", "don't text", "dont text", "no more texts", "stop texting")
NOTE_COLS = ("Taylor's Notes", "Notes", "Being worked on", "Shipping Notes")
_CLOSED = ("active", "disconnected", "cancelled", "canceled", "byod", "returned")


def first_name(customer: str) -> str:
    w = str(customer or "").split()
    return titlecase_name(w[0]) if w else ""


def text_for(customer: str, kind: str = "checkin", lang: str = "") -> str:
    from automations.rc_contact_sync import spanish
    return KINDS[kind][lang or spanish.language(customer)].format(first=first_name(customer))


def lang_from_notes(notes: Sequence[str]) -> str:
    """A customer who asked for a language (the name guess got it wrong) gets
    a note: 'TEXTS IN ENGLISH' / 'TEXTS IN SPANISH'. '' = guess by name."""
    low = " ".join(notes).lower()
    if "texts in english" in low:
        return "en"
    if "texts in spanish" in low:
        return "es"
    return ""


def _who(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def _shipping_delivered(v: str, today: dt.date) -> Optional[dt.date]:
    """'Delivered Nov 23' / 'Delivered 11/23' (Shipping Status) -> the date."""
    v = str(v or "").strip()
    if not v.lower().startswith("delivered"):
        return None
    import re
    rest = re.sub(r"\(.*?\)", "", v[len("delivered"):]).strip(" :-")   # "Delivered Nov 20 (as of 11/26)"
    for fmt in ("%b %d", "%B %d", "%m/%d"):
        try:
            d = dt.datetime.strptime(rest, fmt).date().replace(year=today.year)
            return d if d <= today else d.replace(year=today.year - 1)
        except ValueError:
            pass
    return _parse_date(rest)


def pick_targets(header: Sequence[str], rows: Sequence[Sequence[str]],
                 sent_state: Dict[str, dict], *, today: dt.date,
                 kind: str = "checkin", with_held: bool = False) -> List[Dict]:
    """One target per customer in KINDS[kind]'s window, never texted this kind.

    basis 'active' (default): an Active line, days since the FIRST activation.
    basis 'delivered': NO Active line, at least one line still open (not
    Disconnected/Cancelled/Returned/BYOD), days since the EARLIEST delivery
    on an open line (Delivered date, else Shipping Status 'Delivered <date>').
    Never: anything Not saveable, or a DO_NOT_TEXT note on any line.
    with_held=True also returns the held ones, each with 'held' = why.
    Each: customer, rep, first_active / delivered, days, orders, notes."""
    k = KINDS[kind]
    basis = k.get("basis", "active")
    cols = _hdr(header)
    for need in ("Customer", "Line Status", "Activation Date"):
        if need.lower() not in cols:
            raise RuntimeError("NDS Order Log tab has no %r column -- header: %r"
                               % (need, list(header)))
    by: Dict[str, Dict] = {}
    for row in rows:
        name = _cell(row, cols, "Customer")
        if not name:
            continue
        c = by.setdefault(_who(name), {"customer": name, "rep": "", "first_active": None,
                                       "delivered": None, "active": False, "open": False,
                                       "not_saveable": False, "dnt": "", "orders": [],
                                       "notes": [], "lines": [], "phones": []})
        status = _cell(row, cols, "Line Status").lower()
        c["rep"] = c["rep"] or _cell(row, cols, "Rep")
        if status == "active":
            c["active"] = True
        if status not in _CLOSED:
            c["open"] = True
            dd = _parse_date(_cell(row, cols, "Delivered"))
            if dd is None or dd > today:
                dd = _shipping_delivered(_cell(row, cols, "Shipping Status"), today)
            if dd and dd <= today and (c["delivered"] is None or dd < c["delivered"]):
                c["delivered"] = dd
        if _cell(row, cols, "Being worked on").lower() == NOT_SAVEABLE:
            c["not_saveable"] = True
        for nc in NOTE_COLS:
            v = _cell(row, cols, nc) if nc.lower() in cols else ""
            if v and v not in c["notes"]:
                c["notes"].append(v)
            if nc != "Being worked on" and any(w in v.lower() for w in DO_NOT_TEXT):
                c["dnt"] = c["dnt"] or v
        c["lines"].append("L%s %s" % (_cell(row, cols, "Line"), _cell(row, cols, "Line Status") or "(blank)"))
        ph = RC.norm_phone(_cell(row, cols, "Phone #")) if "phone #" in cols else ""
        if ph and ph not in c["phones"]:
            c["phones"].append(ph)
        d = _parse_date(_cell(row, cols, "Activation Date"))
        if d and (c["first_active"] is None or d < c["first_active"]):
            c["first_active"] = d
        o = (_cell(row, cols, "Wireless Order #"), _cell(row, cols, "DSI #"))
        if any(o) and o not in c["orders"]:
            c["orders"].append(o)
    out = []
    for key, c in by.items():
        if basis == "delivered":
            if c["active"] or not c["open"] or c["delivered"] is None:
                continue
            since = c["delivered"]
        else:
            if not c["active"] or c["first_active"] is None:
                continue
            since = c["first_active"]
        days = (today - since).days
        if days < k["min"] or (k["max"] is not None and days > k["max"]):
            continue
        if key in sent_state:
            continue
        c["days"] = days
        c["held"] = ("Not saveable" if c["not_saveable"]
                     else "note says do not text: %s" % c["dnt"][:120] if c["dnt"] else "")
        if c["held"] and not with_held:
            continue
        out.append(c)
    out.sort(key=lambda c: (c["delivered"] if basis == "delivered" else c["first_active"],
                            c["customer"]))
    return out


def main_number(target: Dict, feed: Sequence[Dict[str, str]], book: Sequence[dict]) -> str:
    """The customer's main contact number: the feed's order phone, else the
    book contact named exactly like the customer (never a '- Line N' one)."""
    for wo, dsi in target["orders"]:
        for f in feed:
            if (wo and f.get("wireless_order") == wo) or (dsi and f.get("order_id") == dsi):
                if RC.norm_phone(f.get("phone", "")):
                    return RC.norm_phone(f["phone"])
    from automations.rc_contact_sync import inbox
    want = _who(target["customer"])
    for c in book:
        if _who(inbox._contact_name(c)) == want:
            nums = inbox._contact_numbers(c)
            if nums:
                return nums[0]
    return ""


def _load_sent(kind: str) -> Dict[str, dict]:
    try:
        return json.loads(KINDS[kind]["sent"].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_sent(kind: str, state: Dict[str, dict]) -> None:
    p = KINDS[kind]["sent"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run(*, live: bool = False, limit: Optional[int] = None, kinds: Sequence[str] = DEFAULT_KINDS,
        today: Optional[dt.date] = None, skip: Sequence[str] = (), log=print) -> int:
    from automations.nds_metrics.order_log_tab import TAB, VANTURA_SHEET_ID
    from automations.rc_contact_sync import delivered, wrapup
    from automations.recruiting_report.fill import _retry, open_by_key

    today = today or dt.date.today()
    log("Activation texts -- %s%s" % (today, "" if live else "  (DRY RUN)"))
    values = _retry(lambda: open_by_key(VANTURA_SHEET_ID).worksheet(TAB).get_all_values())
    if not values:
        log("the %r tab is empty -- nothing to do" % TAB)
        return 0
    plan = []
    for kind in kinds:
        state = _load_sent(kind)
        targets = pick_targets(values[0], values[1:], state, today=today, kind=kind,
                               with_held=True)
        for t in [t for t in targets if t["held"]]:
            log("  - [%s] %s: held -- %s" % (kind, titlecase_name(t["customer"]), t["held"]))
        targets = [t for t in targets if not t["held"]]
        held = [t for t in targets if _who(t["customer"]) in {_who(x) for x in skip}]
        for t in held:
            log("  - [%s] %s: held by --skip" % (kind, titlecase_name(t["customer"])))
        targets = [t for t in targets if t not in held]
        k = KINDS[kind]
        log("%s (%s %s..%s): %d customer(s) not yet texted"
            % (kind, "first delivery" if k.get("basis") == "delivered" else "first activation",
               today - dt.timedelta(days=k["max"]) if k["max"] is not None else "any",
               today - dt.timedelta(days=k["min"]), len(targets)))
        plan.append((kind, state, targets[:limit] if limit else targets))
    if not any(t for _k, _s, t in plan):
        print("[%s] ✅ Finished" % REPORT_ID, flush=True)
        print("=== done ===", flush=True)
        return 0

    feed = delivered.feed_orders(today, log=log)
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    RC.assert_identity(RC.identity(info), creds.get("expected_owner_id") or C.RC_OWNER_ID)
    book = RC.address_book(token, str(creds["contacts_extension_id"]))
    try:
        from_number = RC.sender_number(token)
    except RC.RCError:
        from_number = wrapup.TAYLOR_SMS_NUMBER
    log("sending from %s (Taylor's line), one-to-one, no rep" % from_number)

    sent = skipped = failed = 0
    seen_numbers = set()
    preview: List[str] = []
    for kind, state, targets in plan:
        for t in targets:
            who = titlecase_name(t["customer"])
            phone = main_number(t, feed, book)
            if not phone:
                log("  - [%s] %s (%d days): no main number -- SKIPPED" % (kind, who, t["days"]))
                skipped += 1
                continue
            if phone in seen_numbers:
                log("  - [%s] %s: %s already gets a text this run -- SKIPPED"
                    % (kind, who, RC.e164(phone)))
                skipped += 1
                continue
            seen_numbers.add(phone)
            text = text_for(t["customer"], kind, lang_from_notes(t.get("notes") or []))
            lang = "es" if text.startswith("Hola") else "en"
            since = t["delivered"] if KINDS[kind].get("basis") == "delivered" else t["first_active"]
            line = "[%s] %s | rep %s | %s %s (%d days) | %s | %s" % (
                kind, who, titlecase_name(t["rep"]),
                "delivered" if KINDS[kind].get("basis") == "delivered" else "active",
                since.strftime("%m/%d"), t["days"], lang, RC.e164(phone))
            if not live:
                log("  [dry-run] " + line)
                preview.append(line + "\n  " + text)
                sent += 1
                continue
            try:
                res = RC.send_group_mms(token, from_number, [phone], text)
            except RC.RCError as e:
                failed += 1
                log("  x %s: %s" % (who, str(e)[:200]))
                continue
            state[_who(t["customer"])] = {
                "at": dt.datetime.now().isoformat(timespec="seconds"), "customer": who,
                "to": RC.e164(phone), "msg_id": res.get("id"), "lang": lang,
                "since": (t["delivered"] if KINDS[kind].get("basis") == "delivered"
                          else t["first_active"]).isoformat()}
            _save_sent(kind, state)
            sent += 1
            log("  + " + line)
            time.sleep(6)   # polite pacing, like the delivered text
    log("activation texts: %d %s, %d skipped, %d failed"
        % (sent, "sent" if live else "previewed", skipped, failed))
    if not live and preview:
        try:
            from automations.rc_contact_sync.status_probe import _upload_bytes
            _upload_bytes("\n\n".join(preview).encode(), "Checkin Preview", log=log)
        except Exception as e:  # noqa: BLE001
            log("  (preview upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("[%s] %s Finished" % (REPORT_ID, "⚠" if failed else "✅"), flush=True)
    print("=== done ===", flush=True)
    return 1 if failed else 0


def review(*, today: Optional[dt.date] = None, since: dt.date = dt.date(2026, 10, 15),
           log=print) -> int:
    """READ-ONLY: for every customer a text here could go to (each kind's
    targets, held ones too) and every customer with open lines and nothing
    Active, their notes, lines and WHOLE text chain on Taylor's line -- so a
    person (Claude, 2026-11-27) can read who is not going to activate or
    should not be texted, before anything is sent. -> 'Checkin Review' tab."""
    from automations.nds_metrics.order_log_tab import TAB, VANTURA_SHEET_ID
    from automations.rc_contact_sync import delivered, inbox
    from automations.recruiting_report.fill import _retry, open_by_key
    today = today or dt.date.today()
    values = _retry(lambda: open_by_key(VANTURA_SHEET_ID).worksheet(TAB).get_all_values())
    header, rows = values[0], values[1:]
    tagged: Dict[str, Dict] = {}
    for kind in DEFAULT_KINDS:
        for t in pick_targets(header, rows, _load_sent(kind), today=today, kind=kind, with_held=True):
            tagged.setdefault(_who(t["customer"]), dict(t, tags=[]))["tags"].append(
                kind + (" (HELD: %s)" % t["held"] if t["held"] else ""))
    # every customer with an open line, nothing Active, and a delivery
    KINDS["_open"] = {"basis": "delivered", "min": -100000, "max": None, "sent": None}
    try:
        allc = {_who(t["customer"]): t
                for t in pick_targets(header, rows, {}, today=today, kind="_open", with_held=True)}
    finally:
        KINDS.pop("_open", None)
    cols = _hdr(header)
    for key, t in allc.items():
        tagged.setdefault(key, dict(t, tags=[]))["tags"].append("open, delivered %s, nothing active"
                                                               % t["delivered"].strftime("%m/%d"))
    # open + not delivered yet: straight off the rows
    by_name: Dict[str, Dict] = {}
    for r in rows:
        n = _cell(r, cols, "Customer")
        if n:
            by_name.setdefault(_who(n), []).append(r)
    for key, rs in by_name.items():
        if key in tagged:
            continue
        sts = [_cell(r, cols, "Line Status").lower() for r in rs]
        if "active" in sts or all(x in _CLOSED for x in sts):
            continue
        tagged[key] = {"customer": _cell(rs[0], cols, "Customer"), "rep": _cell(rs[0], cols, "Rep"),
                       "tags": ["open, NOT delivered yet"],
                       "notes": sorted({_cell(r, cols, c) for r in rs for c in NOTE_COLS
                                        if c.lower() in cols and _cell(r, cols, c)}),
                       "lines": ["L%s %s" % (_cell(r, cols, "Line"), _cell(r, cols, "Line Status") or "(blank)")
                                 for r in rs],
                       "phones": [RC.norm_phone(_cell(r, cols, "Phone #")) for r in rs
                                  if RC.norm_phone(_cell(r, cols, "Phone #"))],
                       "orders": [(_cell(r, cols, "Wireless Order #"), _cell(r, cols, "DSI #")) for r in rs]}

    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    RC.assert_identity(RC.identity(info), creds.get("expected_owner_id") or C.RC_OWNER_ID)
    watch_token = RC.token(creds, jwt=creds["watch_jwt"]) if creds.get("watch_jwt") else token
    book = RC.address_book(token, str(creds["contacts_extension_id"]))
    names_of = inbox.name_map(book)
    try:
        own = RC.norm_phone(RC.sender_number(token))
    except Exception:  # noqa: BLE001
        own = ""
    feed = delivered.feed_orders(today, log=log)
    msgs = sorted(inbox._messages_since(watch_token, str(creds["watch_extension_id"]), since),
                  key=lambda x: x.get("creationTime") or "")
    out: List[str] = ["CHECKIN REVIEW %s -- %d customer(s), %d message(s) since %s"
                      % (today, len(tagged), len(msgs), since)]
    for key, t in sorted(tagged.items(), key=lambda kv: kv[0]):
        nums = set(t.get("phones") or [])
        mn = main_number(t, feed, book)
        if mn:
            nums.add(mn)
        for n, nm in names_of.items():
            if _who(nm.split(" - Line")[0]) == key:
                nums.add(n)
        nums.discard(own)
        out.append("")
        out.append("##### %s | rep %s | %s" % (titlecase_name(t["customer"]),
                                             titlecase_name(t.get("rep", "")), "; ".join(t["tags"])))
        out.append("  lines: %s" % ", ".join(t.get("lines") or []))
        for nt in t.get("notes") or []:
            out.append("  note: %s" % " ".join(str(nt).split())[:400])
        chain = [m for m in msgs if nums & ({inbox._sender(m)} | set(inbox._recipients(m)))]
        if not chain:
            out.append("  (no texts)")
        for m in chain:
            snd = inbox._sender(m)
            who = ("OUT" if m.get("direction") == "Outbound"
                   else "IN " if snd in nums else "REP")
            body = " ".join(str(m.get("subject") or "").split()) or "(picture / blank)"
            tpl = inbox.template_of(body)
            if m.get("direction") == "Outbound" and tpl != "typed by a person (not a template)":
                body = "[%s]" % tpl
            out.append("  %s %s %s%s" % (inbox._when(m)[5:], who, body[:260],
                                        "  <%s>" % m.get("messageStatus") if "Failed" in str(m.get("messageStatus")) else ""))
    data = "\n".join(out)
    log("%d customer(s) reviewed, %d bytes" % (len(tagged), len(data)))
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        _upload_bytes(data.encode(), "Checkin Review", log=log)
    except Exception as e:  # noqa: BLE001
        log("  (upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=REPORT_ID,
                                 description="1:1 texts: 'help activating?' (delivered 8+ days, nothing active), "
                                             "'just checking in' at 7-20 and 21+ days active.")
    ap.add_argument("--live", action="store_true", help="send (default: preview only)")
    ap.add_argument("--dry-run", action="store_true", help="preview even when --live is given")
    ap.add_argument("--kind", choices=sorted(KINDS), default=None, help="only this one (default: both)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N customers per kind")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="'today' for the window")
    ap.add_argument("--skip", action="append", default=[], metavar="CUSTOMER",
                    help="hold this customer this run (repeatable; exact name as on the tab)")
    ap.add_argument("--review", action="store_true",
                    help="read-only: notes + whole text chain of every candidate -> 'Checkin Review' tab")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else None
    if a.review:
        return review(today=today)
    return run(live=bool(a.live and not a.dry_run), limit=a.limit, today=today,
               kinds=(a.kind,) if a.kind else DEFAULT_KINDS, skip=a.skip)


if __name__ == "__main__":
    raise SystemExit(main())
