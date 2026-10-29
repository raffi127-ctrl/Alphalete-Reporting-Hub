"""Delivered-phone text — from Taylor's line, one GROUP thread per customer
(Taylor + the SALES REP + the customer), for every crew customer whose
phones the NDS Order Log says are DELIVERED and not yet active.

Carlos 2026-10-29, in order:
  * "every morning, after you sync the contacts and you check to see who
    didn't send the wrap-up text message ... check for people that have had
    their phones delivered. If they have their phones delivered, I want you
    to send this message" — TEXT below, his words verbatim.
  * "You'll send this through Taylor's RingCentral account ... include the
    rep in the group message (the sales rep)."
  * "on the order log, in column S, where it says 'delivered message sent,'
    after you've sent it, go ahead and mark 'yes' ... only for the lines
    that have had it sent."
  * "do that now for any customers that have had their phones delivered and
    are not activated yet."

WHAT COUNTS AS DELIVERED: the tab's *Line Status* reads "Delivered" (the
feed's own word; a line that has activated says "Active" and is left alone,
the message would be nonsense). NOT the "Delivered" DATE column -- on Port
lines the parser still has two columns swapped and that cell carries junk
like 3/17/2025 (README 10/29). Lines are grouped by order, so a customer
with three delivered phones gets ONE text ("your device(s)"), and column S
is marked Yes on exactly those lines.

SOURCES: statuses + column S come from the "NDS Order Log" tab on the
Vantura Master (order_log_tab writes it every morning right before this
runs -- it is the merged, carried truth and the thing Carlos reads). The
customer's CONTACT phone is not on the tab; it comes from the same wireless
feed through guest.guest_customers, joined by Wireless Order # (DSI # as
the fallback). Rep numbers resolve the way the wrap-up sender does: Taylor's
address book, then the alphaletegp Google contacts, then the Daily Update.

SAFETY RAILS, because this one texts CUSTOMERS:
  * DRY RUN by default -- prints every message and recipient pair, uploads
    the whole plan to the control sheet ('Delivered Preview' tab). --live
    sends. The scheduled wrapper passes --live.
  * sent ONCE per line, ever: rc-delivered-sent.json (state) AND column S
    (visible). Either one says Yes -> skipped. Re-runs, crashes and
    double-schedules are absorbed.
  * state is saved and column S is marked per customer, right after each
    send, so a crash halfway never re-texts what already went out.
  * a customer whose phone or rep can't be resolved is SKIPPED and logged,
    never texted alone or to a guessed number.

    python -m automations.rc_contact_sync.delivered            # dry run
    python -m automations.rc_contact_sync.delivered --live --limit 1
    lucy rerun rc_delivered_text                               # preview on Lucy 2
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

REPORT_ID = "rc_delivered_text"
SENT_PATH = C.CONFIG_DIR / "rc-delivered-sent.json"
COL_SENT = "Delivered Message Sent"      # column S on the tab (header-resolved, never by index)
DELIVERED = "delivered"                  # the Line Status word that triggers
# how far back a Delivered line still gets the text (a line delivered weeks ago
# and never activated is a different conversation, not this one)
MAX_ORDER_AGE_DAYS = 31

# Carlos's words, 2026-10-29.
TEXT = ("Hello! I see that your device(s) have been delivered! It will "
        "auto-activate within 24hrs. Wouldn't want it to happen that you "
        "don't have the new phone, so if you need help activating, please "
        "let me know!")


# --- pure pieces (tested) -----------------------------------------------------

def _hdr(header: Sequence[str]) -> Dict[str, int]:
    """Column index by header text, spacing/case-tolerant (the tab is written
    by order_log_tab, but Carlos added column S by hand first)."""
    return {" ".join(str(h).split()).lower(): i for i, h in enumerate(header)}


def _cell(row: Sequence[str], cols: Dict[str, int], name: str) -> str:
    i = cols.get(name.lower())
    return str(row[i]).strip() if i is not None and i < len(row) else ""


def _order_key(row: Sequence[str], cols: Dict[str, int]) -> str:
    return (_cell(row, cols, "Wireless Order #")
            or _cell(row, cols, "DSI #")
            or "%s|%s" % (_cell(row, cols, "Customer"), _cell(row, cols, "Order Date")))


def line_key(order_key: str, line_no: str) -> str:
    return "%s:%s" % (order_key, line_no)


def _parse_date(v: str) -> Optional[dt.date]:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(v or "").strip(), fmt).date()
        except ValueError:
            pass
    return None


def pick_targets(header: Sequence[str], rows: Sequence[Sequence[str]],
                 sent_state: Dict[str, dict], *, today: dt.date) -> List[Dict]:
    """One target per ORDER with at least one line whose Line Status is
    Delivered and that has not been texted (column S != Yes and not in
    state). Active / Shipped / anything else is left alone. Returns, per
    target: customer, rep, wireless_order, dsi, order_date, and the lines
    (sheet row number, line no, device) that will be marked."""
    cols = _hdr(header)
    for need in ("Line Status", "Line", "Customer", "Rep"):
        if need.lower() not in cols:
            raise RuntimeError("NDS Order Log tab has no %r column -- header: %r"
                               % (need, list(header)))
    if COL_SENT.lower() not in cols:
        raise RuntimeError("NDS Order Log tab has no %r column -- nothing to mark, refusing"
                           % COL_SENT)
    oldest = today - dt.timedelta(days=MAX_ORDER_AGE_DAYS)
    targets: "Dict[str, Dict]" = {}
    for i, row in enumerate(rows):
        status = _cell(row, cols, "Line Status").lower()
        if status != DELIVERED:
            continue
        if _cell(row, cols, COL_SENT).lower() == "yes":
            continue
        od = _parse_date(_cell(row, cols, "Order Date"))
        if od and od < oldest:
            continue
        ok = _order_key(row, cols)
        ln = _cell(row, cols, "Line")
        if line_key(ok, ln) in sent_state:
            continue
        t = targets.setdefault(ok, {
            "order_key": ok,
            "customer": _cell(row, cols, "Customer"),
            "rep": _cell(row, cols, "Rep"),
            "wireless_order": _cell(row, cols, "Wireless Order #"),
            "dsi": _cell(row, cols, "DSI #"),
            "order_date": _cell(row, cols, "Order Date"),
            "lines": [],
        })
        t["lines"].append({"sheet_row": i + 2,          # +1 header, +1 one-based
                           "line": ln,
                           "device": _cell(row, cols, "Device")})
    return list(targets.values())


def customer_phone(target: Dict, customers: Sequence[Dict[str, str]]) -> str:
    """The contact phone off the feed's order header, matched by Wireless
    Order # then DSI #. '' when the feed window doesn't carry the order."""
    wo, dsi = target.get("wireless_order", ""), target.get("dsi", "")
    for c in customers:
        if wo and c.get("wireless_order") == wo:
            return c.get("phone", "")
    for c in customers:
        if dsi and c.get("order_id") == dsi:
            return c.get("phone", "")
    return ""


# --- state + sheet ---------------------------------------------------------------

def _load_sent() -> Dict[str, dict]:
    try:
        return json.loads(SENT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_sent(state: Dict[str, dict]) -> None:
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def mark_sent(ws, header: Sequence[str], lines: Sequence[Dict], log=print) -> None:
    """Write Yes into column S for exactly these sheet rows (one batched
    values update; header-resolved column)."""
    from gspread.utils import rowcol_to_a1
    from automations.recruiting_report.fill import _retry
    col = _hdr(header)[COL_SENT.lower()] + 1
    data = [{"range": rowcol_to_a1(l["sheet_row"], col), "values": [["Yes"]]}
            for l in lines]
    _retry(lambda: ws.batch_update(data, value_input_option="RAW"))
    log("    column S marked Yes on row(s) %s"
        % ", ".join(str(l["sheet_row"]) for l in lines))


# --- the run -----------------------------------------------------------------------

def run(*, live: bool = False, limit: Optional[int] = None,
        today: Optional[dt.date] = None, log=print) -> int:
    from automations.nds_metrics.order_log_tab import TAB, VANTURA_SHEET_ID
    from automations.rc_contact_sync import guest, wrapup
    from automations.recruiting_report.fill import _retry, open_by_key

    today = today or dt.date.today()
    log("Delivered-phone text — %s%s" % (today, "" if live else "  (DRY RUN)"))

    # 1. the tab: who is Delivered and not yet texted
    sh = open_by_key(VANTURA_SHEET_ID)
    ws = sh.worksheet(TAB)
    values = _retry(lambda: ws.get_all_values())
    if not values:
        log("the %r tab is empty -- nothing to do" % TAB)
        _manifest([], dry_run=not live, note="tab empty")
        return 0
    header, rows = values[0], values[1:]
    sent_state = _load_sent()
    targets = pick_targets(header, rows, sent_state, today=today)
    n_delivered_lines = sum(len(t["lines"]) for t in targets)
    log("tab: %d line(s); %d customer(s) with %d Delivered line(s) not yet texted"
        % (len(rows), len(targets), n_delivered_lines))
    if not targets:
        _manifest([], dry_run=not live, note="no delivered lines to text")
        print("[%s] ✅ Finished" % REPORT_ID, flush=True)
        print("=== done ===", flush=True)
        return 0

    # 2. contact phones off the feed (the tab has none)
    customers = guest.guest_customers(today - dt.timedelta(days=MAX_ORDER_AGE_DAYS),
                                      today, log=lambda *a, **k: None)
    log("feed: %d crew order(s) with a contact phone in the last %d days"
        % (sum(1 for c in customers if c.get("phone")), MAX_ORDER_AGE_DAYS))

    # 3. RingCentral: who am I, and the reps' numbers
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    me = RC.identity(info)
    RC.assert_identity(me, creds.get("expected_owner_id") or C.RC_OWNER_ID)
    book = RC.address_book(token, str(creds["contacts_extension_id"]))
    rep_names = sorted({t["rep"] for t in targets if t["rep"]})
    reps = wrapup.resolve_reps(book, rep_names, log=log)
    for source, resolver in (("alphaletegp contacts", wrapup.resolve_reps_google),
                             ("Vantura Daily Update", wrapup.resolve_reps_daily_update)):
        unresolved = [r for r in rep_names if r not in reps]
        if not unresolved:
            break
        try:
            for rep, phone in resolver(unresolved, log=log).items():
                reps.setdefault(rep, phone)
                log("  rep %r resolved via %s" % (rep, source))
        except Exception as e:  # noqa: BLE001
            log("  (%s lookup failed: %s: %s)" % (source, type(e).__name__, str(e)[:160]))
    try:
        from_number = RC.sender_number(token)
    except RC.RCError as e:
        from_number = wrapup.TAYLOR_SMS_NUMBER
        log("phone-number endpoint unavailable (%s) — using the canvas's %s"
            % (str(e)[:80], from_number))
    log("sending from %s (Taylor's line)" % from_number)

    # 4. one group text per customer
    if limit:
        targets = targets[:limit]
    sent = skipped = failed = 0
    preview: List[str] = []
    for t in targets:
        who = titlecase_name(t["customer"]) or t["order_key"]
        lines_txt = ", ".join("line %s" % l["line"] for l in t["lines"])
        phone = customer_phone(t, customers)
        if not phone:
            log("  – %s (%s): no contact phone in the feed window — SKIPPED" % (who, lines_txt))
            skipped += 1
            continue
        rep_phone = reps.get(t["rep"])
        if not rep_phone:
            log("  – %s (%s): rep %r unresolved — SKIPPED"
                % (who, lines_txt, titlecase_name(t["rep"])))
            skipped += 1
            continue
        to = [phone, rep_phone]
        if not live:
            log("  [dry-run] %s — %s — group: %s (customer) + %s (%s)"
                % (who, lines_txt, RC.e164(phone), RC.e164(rep_phone),
                   titlecase_name(t["rep"])))
            preview.append("%s | %s | ordered %s | %s\n  customer %s + rep %s (%s)\n  mark Yes on sheet row(s) %s"
                           % (who, lines_txt, t["order_date"], t["wireless_order"] or t["dsi"],
                              RC.e164(phone), RC.e164(rep_phone), titlecase_name(t["rep"]),
                              ", ".join(str(l["sheet_row"]) for l in t["lines"])))
            sent += 1
            continue
        try:
            res = RC.send_group_mms(token, from_number, to, TEXT)
        except RC.RCError as e:
            failed += 1
            log("  ✗ %s: %s" % (who, str(e)[:200]))
            continue
        at = dt.datetime.now().isoformat(timespec="seconds")
        for l in t["lines"]:
            sent_state[line_key(t["order_key"], l["line"])] = {
                "at": at, "customer": who, "to": [RC.e164(n) for n in to],
                "msg_id": res.get("id")}
        _save_sent(sent_state)
        try:
            mark_sent(ws, header, t["lines"], log=log)
        except Exception as e:  # noqa: BLE001 -- the text went out; the state file has it
            log("    (column S mark failed for %s: %s: %s — state file has it, tomorrow's "
                "run will not re-text)" % (who, type(e).__name__, str(e)[:120]))
        sent += 1
        log("  + %s — %s — group with %s" % (who, lines_txt, titlecase_name(t["rep"])))
        time.sleep(6)   # polite pacing; RC business SMS is ~40-60/min
    log("delivered texts: %d %s, %d skipped, %d failed"
        % (sent, "sent" if live else "previewed", skipped, failed))
    if not live and preview:
        try:
            from automations.rc_contact_sync.status_probe import _upload_bytes
            head = "from: %s\n\n%s\n\n" % (from_number, TEXT)
            _upload_bytes((head + "\n\n".join(preview)).encode(), "Delivered Preview", log=log)
        except Exception as e:  # noqa: BLE001
            log("  (preview upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    fails = (["%d send(s) failed" % failed] if failed else [])
    _manifest(fails, dry_run=not live,
              note="%d customer(s) %s, %d skipped" % (sent, "texted" if live else "previewed", skipped))
    print("[%s] %s Finished%s" % (REPORT_ID, "⚠" if fails else "✅",
                                  (" — " + ", ".join(fails)) if fails else ""), flush=True)
    print("=== done ===", flush=True)
    return 1 if failed else 0


def _manifest(failed: List[str], *, dry_run: bool, note: str = "") -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, failed=failed, kind="part", note=note, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        print("  (manifest not written: %s: %s)" % (type(e).__name__, str(e)[:120]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_delivered_text",
        description="Group-text 'your device(s) have been delivered' from Taylor's line "
                    "to every crew customer whose NDS Order Log lines say Delivered, "
                    "and mark column S.")
    ap.add_argument("--live", action="store_true",
                    help="actually send + mark (default: print every message)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N customers (for a careful first --live)")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                    help="'today' for the age window (default: today)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else None
    return run(live=args.live, limit=args.limit, today=today)


if __name__ == "__main__":
    raise SystemExit(main())
