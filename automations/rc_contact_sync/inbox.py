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
    lucy rerun rc_inbox --all --since 2026-10-20 --mark-unread   # + unanswered -> Unread

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
    """Every text since `day`. RingCentral files MMS (the wrap-up with its
    flyer, group-thread replies) under messageType=SMS too -- asking for
    "MMS" is rejected (parameterName messageType, 2026-11-05)."""
    import time as _t
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    out: List[dict] = []
    seen = set()
    for mtype in ("SMS",):
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


def _sender(m: dict) -> str:
    return RC.norm_phone((m.get("from") or {}).get("phoneNumber", ""))


def _recipients(m: dict) -> List[str]:
    return [RC.norm_phone(t.get("phoneNumber", "")) for t in (m.get("to") or [])]


def kind_of(body: str) -> str:
    """What sort of thing a customer sent (finer than bucket_of)."""
    b = (body or "").strip()
    low = b.lower()
    if not b:
        return "blank / attachment only"
    if low.startswith(("liked “", "loved “", "laughed at “", "emphasized “",
                       "questioned “", "disliked “")):
        return "tapback reaction"
    if "order #" in low and "ban" in low:
        return "wrap-up (sent by a rep)"
    return bucket_of(b)


def run_all(since: dt.date, *, mark_unread: bool = False, log=print) -> int:
    """Every text on Taylor's line since `since`.

    Who said what is decided by the SENDER (from.phoneNumber), not by
    which number in the thread is in the book -- in a group thread the rep's
    texts also arrive as Inbound, and the first cut of this attributed them
    to the customer. A customer is a sender whose number is in Taylor's
    contact book (the sync puts every NDS customer and their lines there);
    any other inbound sender is a rep / leader / unknown.

    A customer thread is UNANSWERED when the newest message in it (any
    party, Taylor's outbound or a rep's inbound) is the customer's own.
    --mark-unread flips those customer messages back to Unread in
    RingCentral so they show as waiting."""
    log("RC inbox — ALL conversations since %s%s"
        % (since, "  (+ mark unanswered Unread)" if mark_unread else ""))
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

    msgs = sorted(_messages_since(watch_token, watch_ext, since),
                  key=lambda x: x.get("creationTime") or "")
    log("%d message(s) on the line since %s" % (len(msgs), since))

    # thread key = the customer number in the message (sender for a
    # customer's text; a book number among the recipients otherwise)
    def thread_customer(m: dict) -> str:
        snd = _sender(m)
        if m.get("direction") == "Inbound" and snd in names:
            return snd
        for n in _recipients(m) + [snd]:
            if n in names and n != own:
                return n
        return ""

    out_by_template: Dict[str, List[dict]] = {}
    cust_in: List[dict] = []
    other_in: List[dict] = []
    threads: Dict[str, List[dict]] = {}
    for m in msgs:
        body = m.get("subject") or ""
        tc = thread_customer(m)
        if tc:
            threads.setdefault(tc, []).append(m)
        if m.get("direction") == "Inbound":
            (cust_in if _sender(m) in names else other_in).append(m)
        else:
            out_by_template.setdefault(template_of(body), []).append(m)

    lines: List[str] = []
    lines.append("=== WHAT WE SENT (%d outbound from Taylor's line) ===" % sum(
        len(v) for v in out_by_template.values()))
    for label, ms in sorted(out_by_template.items(), key=lambda kv: -len(kv[1])):
        who = {thread_customer(m) or _recipients(m)[0] if _recipients(m) else "" for m in ms}
        lines.append("  %-40s %4d message(s) to %d number(s)" % (label, len(ms), len(who)))
    for label, _ in TEMPLATES:
        ms = out_by_template.get(label) or []
        if ms:
            lines.append("")
            lines.append("--- the %s, as sent ---" % label)
            lines.append((ms[-1].get("subject") or "").strip())

    # --- what customers sent, by kind ---
    lines.append("")
    lines.append("=== FROM CUSTOMERS (%d texts from %d customers; %d more inbound from reps/others, %d numbers) ==="
                 % (len(cust_in), len({_sender(m) for m in cust_in}),
                    len(other_in), len({_sender(m) for m in other_in})))
    by_kind: Dict[str, List[dict]] = {}
    for m in cust_in:
        by_kind.setdefault(kind_of(m.get("subject") or ""), []).append(m)
    for label, ms in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        lines.append("  %-28s %3d" % (label, len(ms)))

    # --- unanswered threads ---
    unanswered: List[tuple] = []   # (last_customer_msg_time, number, [customer msgs since last reply])
    for n, ms in threads.items():
        last = ms[-1]
        if last.get("direction") == "Inbound" and _sender(last) == n:
            tail = []
            for m in reversed(ms):
                if m.get("direction") == "Inbound" and _sender(m) == n:
                    tail.append(m)
                else:
                    break
            tail.reverse()
            # skip threads whose only unanswered content is a thanks/tapback/blank
            kinds = {kind_of(m.get("subject") or "") for m in tail}
            noise = {"thanks / ok", "tapback reaction", "blank / attachment only"}
            unanswered.append((tail[-1].get("creationTime") or "", n, tail,
                               kinds <= noise))
    unanswered.sort(reverse=True)
    real = [u for u in unanswered if not u[3]]
    soft = [u for u in unanswered if u[3]]
    lines.append("")
    lines.append("=== WAITING ON US: %d customer threads where the customer has the last word (%d need a reply, %d are just thanks/reactions/blank) ==="
                 % (len(unanswered), len(real), len(soft)))
    for _, n, tail, _soft in real:
        lines.append("")
        lines.append("--- %s %s — %d unanswered text(s), newest %s ---"
                     % (RC.e164(n), names.get(n, ""), len(tail), _when(tail[-1])))
        for m in tail[-4:]:
            lines.append("  %s  %s" % (_when(m), (m.get("subject") or "").replace("\n", " ⏎ ")[:300]))
    if soft:
        lines.append("")
        lines.append("--- last word was only thanks / a reaction / blank ---")
        for _, n, tail, _soft in soft:
            lines.append("  %s  %s %s  %s" % (_when(tail[-1]), RC.e164(n), names.get(n, ""),
                                              (tail[-1].get("subject") or "")[:80]))

    # --- every customer text, by kind, for the scrub ---
    for label, ms in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        lines.append("")
        lines.append("--- %s (%d) ---" % (label, len(ms)))
        for m in ms:
            n = _sender(m)
            lines.append("  %s  %s (%s)  %s" % (
                _when(m), RC.e164(n), names.get(n, "?"),
                (m.get("subject") or "").replace("\n", " ⏎ ")[:300]))
    lines.append("")
    lines.append("--- inbound from reps / others (not customer contacts), newest 40 ---")
    for m in other_in[-40:]:
        lines.append("  %s  %s  %s" % (_when(m), RC.e164(_sender(m)),
                                       (m.get("subject") or "").replace("\n", " ⏎ ")[:200]))

    flipped = failed = 0
    if mark_unread:
        lines.append("")
        lines.append("=== MARK UNREAD ===")
        for _, n, tail, _soft in real:
            for m in tail:
                if m.get("readStatus") == "Unread":
                    continue
                try:
                    RC.set_read_status(watch_token, watch_ext, str(m.get("id")), "Unread")
                    flipped += 1
                except RC.RCError as e:
                    failed += 1
                    lines.append("  ✗ %s %s: %s" % (RC.e164(n), names.get(n, ""), str(e)[:200]))
                    if "403" in str(e) or "401" in str(e) or failed >= 3:
                        lines.append("  stopping: the app cannot edit read status (needs EditMessages)")
                        break
            if failed and ("403" in lines[-1] or "stopping" in lines[-1]):
                break
        lines.append("  %d message(s) set Unread, %d failed" % (flipped, failed))

    for ln in lines:
        log(ln)
    try:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        _upload_bytes("\n".join(lines).encode(), TAB, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (tab upload failed: %s: %s)" % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 1 if failed else 0


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
        snd = _sender(m)
        if direction != "Inbound":
            tag = "OUT"
        elif snd in numbers:
            tag = "IN "          # the customer wrote this
        else:
            tag = "REP"          # someone else in the group thread (the rep)
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
    ap.add_argument("--mark-unread", action="store_true",
                    help="with --all: flip every unanswered customer text back "
                         "to Unread in RingCentral (Carlos 2026-11-09)")
    args = ap.parse_args(argv)
    since = (dt.date.fromisoformat(args.since) if args.since
             else dt.date.today() - dt.timedelta(days=30))
    if args.all:
        return run_all(since, mark_unread=args.mark_unread)
    if not args.customer:
        print("✗ give --customer WORD... or --all")
        return 2
    words = [w for a in args.customer for w in a.split()]
    until = (dt.date.fromisoformat(args.until) if args.until
             else C.yesterday())
    return run(words, since, until, inbound_only=args.inbound_only)


if __name__ == "__main__":
    raise SystemExit(main())
