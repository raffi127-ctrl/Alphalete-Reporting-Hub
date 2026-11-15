"""READ-ONLY follow-up review: for the lines of a week that are still not
Active, Disconnected or Cancelled on the NDS Order Log, did the customer
reach out to Taylor's RingCentral line -- by text or by call -- did we
answer, and how long did each conversation run?

Carlos 2026-11-15: "Weekending 11/1: let's look at all of the ones that
aren't canceled, disconnected, or active ... Look through the text messages
to see if any of those customers have reached out ... Check the call log too
to see if they've called. Check and see if we've answered. If we haven't
answered, let me know. If we have answered, let me know how long the convo
was."

    lucy rerun rc_followup --week-ending 2026-11-01
    lucy rerun rc_followup --week-ending 2026-11-01 --since 2026-10-20

How it reads:
  * the customers: the 'NDS Order Log' tab, Week Ending = the date, Line
    Status none of DONE (header-resolved). Every number of the order's
    lines on the tab counts as the customer's, plus Taylor's contact book
    ("<Name>" and "<Name> - Line N") and the feed's contact phone.
  * the texts: Taylor's watched line since the week's first order date.
    IN = from one of the customer's numbers, OUT = from Taylor's line,
    REP = anyone else in the group thread (the rep). The delivered text and
    the wrap-up are Lucy's own (AUTO): they are not an answer to anything.
  * a CONVERSATION is a run of texts with no gap over GAP_HOURS; its length
    is first text to last text. It is ANSWERED when someone on our side
    (Taylor or the rep, not an AUTO text) wrote after the customer's first
    text in it; the customer having the last word is flagged on its own.
  * the calls: the line's call log (needs the app's Read Call Log
    permission; without it the report says so and the texts still stand).

Never writes to RingCentral or to the tab. The report prints and goes to
the control sheet's 'Followup Review' tab (base64, the status_probe relay).

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

REPORT_ID = "rc_followup"
TAB = "Followup Review"
DONE = ("active", "disconnected", "cancelled", "canceled")
GAP_HOURS = 6
ANSWERED_CALLS = ("accepted", "call connected", "answered", "received")


# --- pure helpers (tested without a login) ----------------------------------------

def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def _parse_date(v) -> Optional[dt.date]:
    s = _norm(v)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def pending_customers(header: Sequence[str], rows: Sequence[Sequence[str]],
                      week_ending: dt.date) -> List[Dict]:
    """One entry per order with a line of that week still pending:
    {customer, rep, order_date, dsi, order, lines: [(line, status)],
    phones: every Phone # of the order on the tab (pending or not)}."""
    cols = {_norm(h).lower(): i for i, h in enumerate(header)}
    for need in ("week ending", "customer", "line status", "line", "phone #", "dsi #"):
        if need not in cols:
            raise RuntimeError("NDS Order Log tab has no %r column -- header: %r" % (need, list(header)))

    def cell(r, name):
        i = cols.get(name)
        return _norm(r[i]) if i is not None and i < len(r) else ""

    by_order: Dict[str, Dict] = {}
    phones: Dict[str, List[str]] = {}
    for r in rows:
        key = cell(r, "dsi #") or cell(r, "wireless order #") or cell(r, "customer")
        if not key:
            continue
        p = RC.norm_phone(cell(r, "phone #"))
        if p:
            phones.setdefault(key, [])
            if p not in phones[key]:
                phones[key].append(p)
        if _parse_date(cell(r, "week ending")) != week_ending:
            continue
        if cell(r, "line status").lower() in DONE:
            continue
        o = by_order.setdefault(key, {
            "customer": cell(r, "customer"), "rep": cell(r, "rep"),
            "order_date": cell(r, "order date"), "dsi": cell(r, "dsi #"),
            "order": cell(r, "wireless order #"), "lines": [], "phones": []})
        o["lines"].append((cell(r, "line"), cell(r, "line status") or "(blank)"))
    out = []
    for key, o in by_order.items():
        o["phones"] = list(phones.get(key, []))
        out.append(o)
    out.sort(key=lambda o: (_parse_date(o["order_date"]) or dt.date.min, o["customer"]))
    return out


def conversations(msgs: Sequence[Dict], gap_hours: int = GAP_HOURS) -> List[Dict]:
    """Split one customer's texts (each {when: datetime, tag: IN|OUT|REP|AUTO,
    body}) into conversations: a run with no gap over gap_hours. Each:
    {start, end, minutes, n_in, n_us, n_auto, answered, reply_minutes,
    last_tag, last_body, first_in}. Only runs holding a customer text or one
    of ours typed by a person are returned -- a lone AUTO text is not a
    conversation."""
    ordered = sorted(msgs, key=lambda m: m["when"])
    runs: List[List[Dict]] = []
    for m in ordered:
        if runs and (m["when"] - runs[-1][-1]["when"]) <= dt.timedelta(hours=gap_hours):
            runs[-1].append(m)
        else:
            runs.append([m])
    out = []
    for run in runs:
        n_in = sum(1 for m in run if m["tag"] == "IN")
        n_us = sum(1 for m in run if m["tag"] in ("OUT", "REP"))
        n_auto = sum(1 for m in run if m["tag"] == "AUTO")
        if not n_in and not n_us:
            continue
        first_in = next((m for m in run if m["tag"] == "IN"), None)
        reply = None
        if first_in is not None:
            reply = next((m for m in run if m["tag"] in ("OUT", "REP") and m["when"] >= first_in["when"]
                          and m is not first_in), None)
        real = [m for m in run if m["tag"] != "AUTO"] or run
        last = real[-1]
        out.append({
            "start": run[0]["when"], "end": run[-1]["when"],
            "minutes": int(round((run[-1]["when"] - run[0]["when"]).total_seconds() / 60.0)),
            "n_in": n_in, "n_us": n_us, "n_auto": n_auto,
            "answered": bool(first_in is not None and reply is not None),
            "reply_minutes": (int(round((reply["when"] - first_in["when"]).total_seconds() / 60.0))
                              if first_in is not None and reply is not None else None),
            "last_tag": last["tag"], "last_body": _norm(last.get("body"))[:160],
            "first_in": first_in is not None,
        })
    return out


def span(minutes: int) -> str:
    """'under a minute' / '12 min' / '2 h 05 min' / '1 d 3 h'."""
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return "%d min" % minutes
    if minutes < 24 * 60:
        return "%d h %02d min" % (minutes // 60, minutes % 60)
    return "%d d %d h" % (minutes // (24 * 60), (minutes % (24 * 60)) // 60)


def call_line(c: Dict) -> str:
    d = int(c.get("seconds") or 0)
    return "%s  %s call  %s  %d:%02d" % (c["when"].strftime("%m/%d %H:%M"),
                                         "IN " if c["inbound"] else "OUT", c.get("result") or "?",
                                         d // 60, d % 60)


def verdict(convs: Sequence[Dict], calls: Sequence[Dict]) -> str:
    """The one-line answer per customer."""
    texted_in = [c for c in convs if c["first_in"]]
    called_in = [c for c in calls if c["inbound"]]
    if not texted_in and not called_in:
        return "NO CONTACT FROM THE CUSTOMER"
    open_texts = [c for c in texted_in if not c["answered"]]
    last = texted_in[-1] if texted_in else None
    missed = [c for c in called_in if (c.get("result") or "").lower() not in ANSWERED_CALLS]
    bits = []
    if open_texts:
        bits.append("NOT ANSWERED (%d text conversation(s) with no reply)" % len(open_texts))
    elif last is not None and last["last_tag"] == "IN":
        bits.append("ANSWERED, but the customer has the last word")
    elif texted_in:
        bits.append("ANSWERED")
    if called_in:
        bits.append("%d inbound call(s), %d not picked up" % (len(called_in), len(missed)))
    return "; ".join(bits)


# --- RingCentral -----------------------------------------------------------------

def _local(raw: str) -> Optional[dt.datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(raw or "", fmt).replace(tzinfo=dt.timezone.utc).astimezone()
        except ValueError:
            continue
    return None


def call_log(token: str, ext_id: str, since: dt.date, log=print) -> Optional[List[Dict]]:
    """The line's voice calls since `since`; None when the app cannot read
    the call log (no Read Call Log permission) -- said in the log, never
    silently empty."""
    import time as _t
    start = dt.datetime.combine(since, dt.time.min).astimezone()
    params = {"type": "Voice", "view": "Simple", "perPage": 250,
              "dateFrom": start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out: List[Dict] = []
    page = 1
    while True:
        params["page"] = page
        try:
            data = RC._get(token, "/restapi/v1.0/account/~/extension/%s/call-log" % ext_id, params)
        except RC.RCError as e:
            log("  call log NOT readable: %s" % str(e)[:300])
            return None
        for r in data.get("records", []):
            when = _local(r.get("startTime") or "")
            if when is None:
                continue
            out.append({"when": when, "inbound": (r.get("direction") or "").lower() == "inbound",
                        "from": RC.norm_phone((r.get("from") or {}).get("phoneNumber", "")),
                        "to": RC.norm_phone((r.get("to") or {}).get("phoneNumber", "")),
                        "result": r.get("result") or "", "seconds": r.get("duration") or 0})
        if not data.get("navigation", {}).get("nextPage"):
            break
        page += 1
        _t.sleep(0.3)
    return out


def run(week_ending: dt.date, since: Optional[dt.date] = None, log=print) -> int:
    from automations.nds_metrics import order_log_tab as T
    from automations.rc_contact_sync import inbox
    from automations.recruiting_report.fill import open_by_key, _retry

    lines: List[str] = []

    def say(msg=""):
        log(msg)
        lines.append(str(msg))

    ws = open_by_key(T.VANTURA_SHEET_ID).worksheet(T.TAB)
    rows = _retry(lambda: ws.get_all_values())
    custs = pending_customers(rows[0], rows[1:], week_ending) if rows else []
    say("Follow-up review -- week ending %s, lines not Active / Disconnected / Cancelled"
        % week_ending.strftime("%m/%d/%Y"))
    say("%d customer(s), %d line(s)" % (len(custs), sum(len(c["lines"]) for c in custs)))
    if not custs:
        print("=== done ===", flush=True)
        return 0
    dates = [d for d in (_parse_date(c["order_date"]) for c in custs) if d]
    since = since or ((min(dates) if dates else week_ending - dt.timedelta(days=7)))
    say("texts and calls on Taylor's line since %s" % since)

    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    RC.assert_identity(RC.identity(info), creds.get("expected_owner_id") or C.RC_OWNER_ID)
    contacts_ext = str(creds["contacts_extension_id"])
    watch_ext = str(creds["watch_extension_id"])
    watch_token = RC.token(creds, jwt=creds["watch_jwt"]) if creds.get("watch_jwt") else token

    book = RC.address_book(token, contacts_ext)
    feed_phone: Dict[str, str] = {}
    try:
        from automations.rc_contact_sync import delivered
        for o in delivered.feed_orders(dt.date.today(), log=lambda *a, **k: None):
            p = RC.norm_phone(o.get("phone") or "")
            if p:
                for k in (o.get("wireless_order"), o.get("order_id")):
                    if k:
                        feed_phone[str(k)] = p
    except Exception as e:  # noqa: BLE001
        say("  (feed contact phones skipped: %s)" % type(e).__name__)

    msgs = inbox._messages_since(watch_token, watch_ext, since)
    say("%d text(s) on the line since %s" % (len(msgs), since))
    calls = call_log(watch_token, watch_ext, since, log=say)
    if calls is None:
        say("  -> calls are NOT in this review. In the RingCentral developer console, the app "
            "'Alphalete B2B Contact Sync' needs the 'Read Call Log' permission (same place "
            "Edit Messages was added on 11/9).")
    else:
        say("%d call(s) on the line since %s" % (len(calls), since))
    say("")

    n_none = n_open = n_ok = 0
    for c in custs:
        numbers = set(c["phones"])
        for con in inbox.matching_contacts(book, c["customer"].split()):
            numbers.update(inbox._contact_numbers(con))
        for k in (c["order"], c["dsi"]):
            if k and k in feed_phone:
                numbers.add(feed_phone[k])
        thread = []
        for m in msgs:
            if not any(n in numbers for n in RC._msg_numbers(m)):
                continue
            when = _local(m.get("creationTime") or "")
            if when is None:
                continue
            body = m.get("subject") or ""
            if (m.get("direction") or "") != "Inbound":
                tag = "AUTO" if not inbox.template_of(body).startswith("typed by") else "OUT"
            elif inbox._sender(m) in numbers:
                tag = "IN"
            else:
                tag = "REP"
            thread.append({"when": when, "tag": tag, "body": body})
        convs = conversations(thread)
        mine = [k for k in (calls or []) if k["from"] in numbers or k["to"] in numbers]
        v = verdict(convs, mine)
        if v.startswith("NO CONTACT"):
            n_none += 1
        elif "NOT ANSWERED" in v or "not picked up" in v and ", 0 not picked up" not in v:
            n_open += 1
        else:
            n_ok += 1
        say("%s  (rep %s, ordered %s)" % (c["customer"], c["rep"], c["order_date"]))
        say("  lines: %s" % ", ".join("L%s %s" % l for l in c["lines"]))
        say("  -> %s" % v)
        autos = sum(1 for m in thread if m["tag"] == "AUTO")
        if autos:
            say("  our automatic texts to them: %d" % autos)
        for k in convs:
            if not k["first_in"]:
                say("  %s  we texted (no customer text): %d from us, %s"
                    % (k["start"].strftime("%m/%d %H:%M"), k["n_us"], span(k["minutes"])))
                continue
            say("  %s  conversation: %s long, %d from the customer, %d from us%s"
                % (k["start"].strftime("%m/%d %H:%M"), span(k["minutes"]), k["n_in"], k["n_us"],
                   (", first reply after %s" % span(k["reply_minutes"])) if k["answered"]
                   else " -- NO REPLY"))
            if k["last_tag"] == "IN":
                say("      customer's last text: %s" % k["last_body"])
        for k in sorted(mine, key=lambda x: x["when"]):
            say("  " + call_line(k))
        say("")
    say("TOTAL: %d never reached out, %d waiting on us, %d answered" % (n_none, n_open, n_ok))
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        _upload_bytes("\n".join(lines).encode(), TAB, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (tab upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rc_followup",
                                 description="READ-ONLY: pending lines of a week -- did the customer "
                                             "text or call Taylor's line, and did we answer?")
    ap.add_argument("--week-ending", required=True, metavar="YYYY-MM-DD",
                    help="the Week Ending value on the NDS Order Log (a Sunday)")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="read texts/calls from this date (default: the week's first order date)")
    a = ap.parse_args(argv)
    return run(dt.date.fromisoformat(a.week_ending),
               dt.date.fromisoformat(a.since) if a.since else None)


if __name__ == "__main__":
    import sys
    sys.exit(main())
