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


def first_name(customer: str) -> str:
    w = str(customer or "").split()
    return titlecase_name(w[0]) if w else ""


def text_for(customer: str, kind: str = "checkin") -> str:
    from automations.rc_contact_sync import spanish
    return KINDS[kind][spanish.language(customer)].format(first=first_name(customer))


def _who(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def pick_targets(header: Sequence[str], rows: Sequence[Sequence[str]],
                 sent_state: Dict[str, dict], *, today: dt.date,
                 kind: str = "checkin") -> List[Dict]:
    """One target per customer whose first activation is KINDS[kind]'s
    min..max days ago, with an Active line, nothing Not saveable, never texted. Each:
    customer, rep, first_active, days, orders [(wireless_order, dsi)]."""
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
                                       "active": False, "not_saveable": False, "orders": []})
        if _cell(row, cols, "Line Status").lower() == "active":
            c["active"] = True
            c["rep"] = c["rep"] or _cell(row, cols, "Rep")
        if _cell(row, cols, "Being worked on").lower() == NOT_SAVEABLE:
            c["not_saveable"] = True
        d = _parse_date(_cell(row, cols, "Activation Date"))
        if d and (c["first_active"] is None or d < c["first_active"]):
            c["first_active"] = d
        o = (_cell(row, cols, "Wireless Order #"), _cell(row, cols, "DSI #"))
        if any(o) and o not in c["orders"]:
            c["orders"].append(o)
    out = []
    for key, c in by.items():
        if not c["active"] or c["not_saveable"] or c["first_active"] is None:
            continue
        days = (today - c["first_active"]).days
        if not (KINDS[kind]["min"] <= days <= KINDS[kind]["max"]):
            continue
        if key in sent_state:
            continue
        c["days"] = days
        out.append(c)
    out.sort(key=lambda c: (c["first_active"], c["customer"]))
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


def run(*, live: bool = False, limit: Optional[int] = None, kinds: Sequence[str] = ("recent", "checkin"),
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
        targets = pick_targets(values[0], values[1:], state, today=today, kind=kind)
        held = [t for t in targets if _who(t["customer"]) in {_who(x) for x in skip}]
        for t in held:
            log("  - [%s] %s: held by --skip" % (kind, titlecase_name(t["customer"])))
        targets = [t for t in targets if t not in held]
        k = KINDS[kind]
        log("%s (first activation %s..%s): %d customer(s) not yet texted"
            % (kind, today - dt.timedelta(days=k["max"]), today - dt.timedelta(days=k["min"]),
               len(targets)))
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
                log("  - [%s] %s (active %s, %d days): no main number -- SKIPPED"
                    % (kind, who, t["first_active"].strftime("%m/%d"), t["days"]))
                skipped += 1
                continue
            if phone in seen_numbers:
                log("  - [%s] %s: %s already gets a text this run -- SKIPPED"
                    % (kind, who, RC.e164(phone)))
                skipped += 1
                continue
            seen_numbers.add(phone)
            text = text_for(t["customer"], kind)
            lang = "es" if text.startswith("Hola") else "en"
            line = "[%s] %s | rep %s | active %s (%d days) | %s | %s" % (
                kind, who, titlecase_name(t["rep"]), t["first_active"].strftime("%m/%d"),
                t["days"], lang, RC.e164(phone))
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
                "first_active": t["first_active"].isoformat()}
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=REPORT_ID,
                                 description="1:1 texts by days since activation: 'recently activated' "
                                             "(0-13 days) and 'just checking in' (14-30 days).")
    ap.add_argument("--live", action="store_true", help="send (default: preview only)")
    ap.add_argument("--dry-run", action="store_true", help="preview even when --live is given")
    ap.add_argument("--kind", choices=sorted(KINDS), default=None, help="only this one (default: both)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N customers per kind")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="'today' for the window")
    ap.add_argument("--skip", action="append", default=[], metavar="CUSTOMER",
                    help="hold this customer this run (repeatable; exact name as on the tab)")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else None
    return run(live=bool(a.live and not a.dry_run), limit=a.limit, today=today,
               kinds=(a.kind,) if a.kind else ("recent", "checkin"), skip=a.skip)


if __name__ == "__main__":
    raise SystemExit(main())
