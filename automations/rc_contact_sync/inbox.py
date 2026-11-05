"""READ-ONLY: what did a customer write to Taylor's RingCentral line, and
what did we send them? (Carlos 2026-11-05: "look through our text. did
erika gutierrez reach out to us")

Finds the customer's numbers two ways -- every contact in Taylor's book
whose name holds all the --customer words (the main contact AND the
"<Name> - Line N" contacts the sync creates), plus any feed order in the
window with that customer name -- then prints every SMS in the watched
store since --since that touches one of those numbers, oldest first:

    2026-11-01 14:02  IN   +14695315219  (Line 2)  "hi is this taylor..."
    2026-11-01 14:05  OUT  +14695315219            "Hello! ..."

The whole transcript also goes to the control sheet's 'RC Inbox' tab
(base64, the status_probe relay) so the mini can read it whole.

    lucy rerun rc_inbox --customer "Erika Gutierrez" --since 2026-10-20
    lucy rerun rc_inbox --all --since 2026-10-20        # EVERY NDS customer: what we
                                                       # send (by template) + every reply

Never writes to RingCentral; identity is asserted before the read.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

REPORT_ID = "rc_inbox"
TAB = "RC Inbox"


def _contact_name(c: dict) -> str:
    return " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x).strip()


def _contact_numbers(c: dict) -> List[str]:
    out = []
    for k in ("mobilePhone", "homePhone", "businessPhone", "otherPhone",
              "homePhone2", "businessPhone2"):
        v = RC.norm_phone(c.get(k) or "")
        if v:
            out.append(v)
    return out


def matching_contacts(book: List[dict], words: List[str]) -> List[dict]:
    want = [w.lower() for w in words if w]
    hits = []
    for c in book:
        name = _contact_name(c).lower()
        if name and all(w in name for w in want):
            hits.append(c)
    return hits


def feed_numbers(words: List[str], since: dt.date, until: dt.date,
                 log=print) -> Dict[str, str]:
    """{number: label} for every feed order whose customer name holds the
    words -- the main number and each line's number."""
    out: Dict[str, str] = {}
    try:
        from automations.rc_contact_sync import guest
        custs = guest.guest_customers(since, until, log=lambda *a, **k: None)
    except Exception as e:  # noqa: BLE001
        log("  (feed lookup skipped: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return out
    want = [w.lower() for w in words]
    for cu in custs:
        name = (cu.get("customer_name") or "").lower()
        if not all(w in name for w in want):
            continue
        main = RC.norm_phone(cu.get("phone") or "")
        if main:
            out.setdefault(main, "main (%s, rep %s)" % (cu.get("day"), cu.get("rep")))
        for ln in cu.get("lines") or []:
            p = RC.norm_phone(guest.line_phone(ln) or "")
            if p and p != main:
                out.setdefault(p, "Line %s" % (ln.get("line") or "?"))
        for p in cu.get("alt_phones") or []:
            p = RC.norm_phone(p)
            if p:
                out.setdefault(p, "alt")
    return out


def _messages_since(token: str, ext_id: str, day: dt.date) -> List[dict]:
    """SMS *and* MMS (the wrap-up goes out as an MMS with the flyer, and a
    reply inside that group thread can come back typed MMS)."""
    import time as _t
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    out: List[dict] = []
    seen = set()
    for mtype in ("SMS", "MMS"):
        params = {"messageType": mtype, "perPage": 250,
                  "dateFrom": start.astimezone(dt.timezone.utc)
                                   .strftime("%Y-%m-%dT%H:%M:%SZ")}
        page = 1
        while True:
            params["page"] = page
            data = RC._get(token,
                           "/restapi/v1.0/account/~/extension/%s/message-store"
                           % ext_id, params)
            for m in data.get("records", []):
                if m.get("id") in seen:
                    continue
                seen.add(m.get("id"))
                out.append(m)
            if not data.get("navigation", {}).get("nextPage"):
                break
            page += 1
            _t.sleep(0.3)
    return out


# The texts Lucy sends on her own, by their opening words.
TEMPLATES = (
    ("delivered text (rc_delivered_text)",
     "hello! i see that your device(s) have been delivered"),
    ("wrap-up (rc_wrapup)", "thank you for choosing at&t! here's your order wrap-up"),
)


def template_of(body: str) -> str:
    b = (body or "").strip().lower()
    for label, needle in TEMPLATES:
        if needle in b:
            return label
    return "typed by a person (not a template)"


BUCKETS = (
    ("activation help", ("activat", "sim", "esim", "set up", "setup", "turn on",
                         "not working", "doesn't work", "won't", "wont")),
    ("delivery / shipping", ("deliver", "package", "tracking", "ups", "fedex",
                             "shipped", "arrive", "received", "recieved")),
    ("billing / charges", ("bill", "charge", "payment", "price", "cost", "pay ",
                           "autopay", "auto pay", "credit")),
    ("cancel / return", ("cancel", "return", "refund", "send back", "don't want",
                         "dont want")),
    ("trade-in", ("trade", "old phone")),
    ("thanks / ok", ("thank", "thanks", "ok", "okay", "got it", "perfect", "great",
                     "sounds good", "will do", "👍", "gracias")),
    ("wrong number / stop", ("wrong number", "stop", "who is this", "who's this",
                             "unsubscribe")),
)


def bucket_of(body: str) -> str:
    b = " " + (body or "").strip().lower() + " "
    for label, needles in BUCKETS:
        if any(n in b for n in needles):
            return label
    return "question / other"


def name_map(book: List[dict]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in book:
        for n in _contact_numbers(c):
            out.setdefault(n, _contact_name(c))
    return out


def run_all(since: dt.date, *, log=print) -> int:
    """Every text on Taylor's line since `since`: what Lucy sent (by
    template), what people typed by hand, and every reply that came back --
    bucketed, with the contact's name, and whether we answered it."""
    log("RC inbox — ALL conversations since %s" % since)
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    me = RC.identity(info)
    RC.assert_identity(me, creds.get("expected_owner_id") or C.RC_OWNER_ID)
    contacts_ext = str(creds["contacts_extension_id"])
    watch_ext = str(creds["watch_extension_id"])
    watch_token = token
    if creds.get("watch_jwt"):
        watch_token = RC.token(creds, jwt=creds["watch_jwt"])
    names = name_map(RC.address_book(token, contacts_ext))
    try:
        own = RC.norm_phone(RC.sender_number(token))
    except Exception:  # noqa: BLE001
        own = RC.norm_phone("945-337-2199")

    msgs = _messages_since(watch_token, watch_ext, since)
    log("%d message(s) on the line since %s" % (len(msgs), since))

    def other_party(m: dict) -> str:
        nums = [n for n in RC._msg_numbers(m) if n != own]
        # a group text lists the customer AND the rep; prefer a number that
        # is a known customer contact
        for n in nums:
            if n in names:
                return n
        return nums[0] if nums else ""

    out_by_template: Dict[str, List[dict]] = {}
    inbound: List[dict] = []
    for m in msgs:
        body = m.get("subject") or ""
        if m.get("direction") == "Inbound":
            inbound.append(m)
        else:
            out_by_template.setdefault(template_of(body), []).append(m)

    lines: List[str] = []
    lines.append("=== WHAT WE SENT (%d outbound) ===" % sum(
        len(v) for v in out_by_template.values()))
    for label, ms in sorted(out_by_template.items(), key=lambda kv: -len(kv[1])):
        who = {other_party(m) for m in ms}
        lines.append("  %-40s %4d message(s) to %d number(s)" % (label, len(ms), len(who)))
    for label, _ in TEMPLATES:
        ms = out_by_template.get(label) or []
        if ms:
            lines.append("")
            lines.append("--- the %s, as sent ---" % label)
            lines.append((ms[-1].get("subject") or "").strip())
    typed = out_by_template.get("typed by a person (not a template)") or []
    if typed:
        lines.append("")
        lines.append("--- typed by a person (%d), newest 25 ---" % len(typed))
        for m in sorted(typed, key=lambda x: x.get("creationTime") or "")[-25:]:
            n = other_party(m)
            lines.append("  %s  -> %s %s  %s" % (
                _when(m), RC.e164(n), ("(%s)" % names[n]) if n in names else "",
                (m.get("subject") or "").replace("\n", " ⏎ ")[:220]))

    # replies: bucket + did we answer after it
    lines.append("")
    lines.append("=== REPLIES FROM CUSTOMERS (%d inbound) ===" % len(inbound))
    by_bucket: Dict[str, List[dict]] = {}
    for m in inbound:
        by_bucket.setdefault(bucket_of(m.get("subject") or ""), []).append(m)
    for label, ms in sorted(by_bucket.items(), key=lambda kv: -len(kv[1])):
        lines.append("  %-24s %3d" % (label, len(ms)))
    # per-number: last direction tells whether the last word was theirs
    last_dir: Dict[str, str] = {}
    for m in sorted(msgs, key=lambda x: x.get("creationTime") or ""):
        last_dir[other_party(m)] = m.get("direction") or ""
    unanswered = sorted({other_party(m) for m in inbound
                         if last_dir.get(other_party(m)) == "Inbound"})
    lines.append("  conversations where the customer has the last word: %d" % len(unanswered))
    for label, ms in sorted(by_bucket.items(), key=lambda kv: -len(kv[1])):
        lines.append("")
        lines.append("--- %s (%d) ---" % (label, len(ms)))
        for m in sorted(ms, key=lambda x: x.get("creationTime") or ""):
            n = other_party(m)
            flag = "  [UNANSWERED]" if last_dir.get(n) == "Inbound" else ""
            lines.append("  %s  %s %s  %s%s" % (
                _when(m), RC.e164(n), ("(%s)" % names[n]) if n in names else "(not in book)",
                (m.get("subject") or "").replace("\n", " ⏎ ")[:300], flag))
    for ln in lines:
        log(ln)
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        _upload_bytes("\n".join(lines).encode(), TAB, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (tab upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 0


def _when(m: dict) -> str:
    raw = m.get("creationTime") or ""
    try:
        t = dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        try:
            t = dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return raw
    return (t.replace(tzinfo=dt.timezone.utc).astimezone()
            .strftime("%Y-%m-%d %H:%M"))


def run(words: List[str], since: dt.date, until: dt.date, *,
        inbound_only: bool = False, log=print) -> int:
    log("RC inbox — customer %r, %s..now%s"
        % (" ".join(words), since, "  (inbound only)" if inbound_only else ""))
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    me = RC.identity(info)
    RC.assert_identity(me, creds.get("expected_owner_id") or C.RC_OWNER_ID)
    contacts_ext = str(creds["contacts_extension_id"])
    watch_ext = str(creds["watch_extension_id"])
    watch_token = token
    if creds.get("watch_jwt"):
        watch_token = RC.token(creds, jwt=creds["watch_jwt"])

    numbers: Dict[str, str] = {}
    book = RC.address_book(token, contacts_ext)
    for c in matching_contacts(book, words):
        for n in _contact_numbers(c):
            numbers.setdefault(n, "contact: %s" % _contact_name(c))
    log("book: %d contact(s) match, %d number(s)" % (
        len(matching_contacts(book, words)), len(numbers)))
    for n, label in feed_numbers(words, since, until, log=log).items():
        numbers.setdefault(n, "feed: %s" % label)
    if not numbers:
        log("no numbers found for %r in the book or the feed — nothing to read"
            % " ".join(words))
        print("=== done ===", flush=True)
        return 0
    for n, label in sorted(numbers.items()):
        log("  %s  %s" % (RC.e164(n), label))

    msgs = _messages_since(watch_token, watch_ext, since)
    log("%d SMS/MMS on the watched line since %s" % (len(msgs), since))
    rows: List[str] = []
    for m in msgs:
        nums = RC._msg_numbers(m)
        hit = [n for n in nums if n in numbers]
        if not hit:
            continue
        direction = (m.get("direction") or "?")
        if inbound_only and direction != "Inbound":
            continue
        tag = "IN " if direction == "Inbound" else "OUT"
        body = (m.get("subject") or "").replace("\n", " ⏎ ")
        rows.append("%s  %s  %s  (%s)  %s" % (
            _when(m), tag, RC.e164(hit[0]), numbers[hit[0]], body))
    rows.sort()
    inbound = sum(1 for r in rows if "  IN   " in r or "  IN  " in r)
    log("%d message(s) with %s — %d inbound (from the customer)"
        % (len(rows), " ".join(words), inbound))
    for r in rows:
        log("  " + r)
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        head = "customer: %s\nsince: %s\nnumbers:\n%s\n\n" % (
            " ".join(words), since,
            "\n".join("  %s  %s" % (RC.e164(n), l) for n, l in sorted(numbers.items())))
        _upload_bytes((head + "\n".join(rows)).encode(), TAB, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (tab upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_inbox",
        description="READ-ONLY transcript of a customer's texts with Taylor's "
                    "RingCentral line.")
    ap.add_argument("--customer", nargs="+", default=None, metavar="WORD",
                    help="name words, all must appear (e.g. Erika Gutierrez)")
    ap.add_argument("--all", action="store_true",
                    help="every conversation on the line: what we send by "
                         "template, every reply bucketed, unanswered flagged")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="default: 30 days back")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                    help="feed window end (default: yesterday)")
    ap.add_argument("--inbound-only", action="store_true",
                    help="only what the customer wrote to us")
    args = ap.parse_args(argv)
    since = (dt.date.fromisoformat(args.since) if args.since
             else dt.date.today() - dt.timedelta(days=30))
    if args.all:
        return run_all(since)
    if not args.customer:
        print("✗ give --customer WORD... or --all")
        return 2
    words = [w for a in args.customer for w in a.split()]
    until = (dt.date.fromisoformat(args.until) if args.until
             else C.yesterday())
    return run(words, since, until, inbound_only=args.inbound_only)


if __name__ == "__main__":
    raise SystemExit(main())
