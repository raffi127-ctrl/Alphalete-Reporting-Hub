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
    lucy rerun rc_inbox --customer Gutierrez --since 2026-10-20 --all-directions

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

    msgs = RC.sms_since(watch_token, watch_ext, since)
    log("%d SMS on the watched line since %s" % (len(msgs), since))
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
    ap.add_argument("--customer", nargs="+", required=True, metavar="WORD",
                    help="name words, all must appear (e.g. Erika Gutierrez)")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="default: 30 days back")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                    help="feed window end (default: yesterday)")
    ap.add_argument("--inbound-only", action="store_true",
                    help="only what the customer wrote to us")
    args = ap.parse_args(argv)
    words = [w for a in args.customer for w in a.split()]
    since = (dt.date.fromisoformat(args.since) if args.since
             else dt.date.today() - dt.timedelta(days=30))
    until = (dt.date.fromisoformat(args.until) if args.until
             else C.yesterday())
    return run(words, since, until, inbound_only=args.inbound_only)


if __name__ == "__main__":
    raise SystemExit(main())
