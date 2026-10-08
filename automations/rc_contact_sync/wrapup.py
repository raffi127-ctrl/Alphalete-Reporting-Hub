"""Send the D2D wrap-up to the guest customers nobody texted — one GROUP
thread per customer: Taylor's line + the SALES REP + the customer.

Carlos 2026-10-08, in order:
  * "with the people who haven't been texted can you start a group text and
    send them what we're suppose to send them?"
  * "dont send one big thread. send an indivudal group with taylor (which is
    the number you're texting from) the sales rep, and the customer"
  * the content is the #alphalete-gp-sales "D2D Wrap Up" canvas (canvas id
    F095EC26XHQ), read off Slack 2026-10-08 — the bullet list below plus the
    'THANK YOU FOR CHOOSING AT&T' flyer image.
  * "reps numbers should be in the contact list" — Taylor's RingCentral
    address book, resolved by name at run time (the same unique-hit-only
    matcher the roster uses everywhere else; REP_PHONE_OVERRIDES wins).

FILLED PER CUSTOMER, from Raf's SaraPlus export (the raf_guest envelope):
  Order #  <- 'Wireless Order #'   (the 99-… number the canvas shows)
  BAN #    <- 'Wireless Acct #'
  PIN      <- NOT in SaraPlus. The line reads "your rep will confirm your
              4-digit PIN here" until Carlos names a source — the rep is in
              the thread, so the thread is where it lands either way.

FLYER: attached when resources/rc_contact_sync/wrapup_flyer.png exists in
the repo; otherwise the text goes alone and the preview says so.

SAFETY RAILS, because this one texts CUSTOMERS:
  * DRY RUN by default — prints every message, every recipient pair, and
    every rep it could not resolve. --live sends.
  * one state file (rc-wrapup-sent.json): a customer is texted ONCE, ever.
    Re-runs, crashes and double-schedules are all absorbed by it.
  * a customer whose rep can't be resolved is SKIPPED and listed — never
    sent half a group.

    python -m automations.rc_contact_sync.wrapup --since 2026-09-29            # preview
    python -m automations.rc_contact_sync.wrapup --since 2026-09-29 --find-reps
    python -m automations.rc_contact_sync.wrapup --since 2026-09-29 --live
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.shared.name_case import titlecase_name
from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

REPO_ROOT = Path(__file__).resolve().parents[2]
# Fetched once per machine by --fetch-flyer (the config area, not the repo,
# so a binary never has to ride through git); the repo path is the fallback
# in case someone commits it instead.
FLYER_PATH = C.CONFIG_DIR / "wrapup_flyer.png"
FLYER_REPO_PATH = REPO_ROOT / "resources" / "rc_contact_sync" / "wrapup_flyer.png"
# The flyer image inside the #alphalete-gp-sales "D2D Wrap Up" canvas
# (canvas F095EC26XHQ), read off Slack 2026-10-08.
FLYER_FILE_ID = "F0C7C8MAHHD"
SENT_PATH = C.CONFIG_DIR / "rc-wrapup-sent.json"
TODO_URL = ("https://drive.google.com/file/d/"
            "10_l7f3VaQ2pjPuHTFR98_3fDsLjo1qtc/view")

# SaraPlus rep spelling -> a phone, when the address book can't answer.
REP_PHONE_OVERRIDES: Dict[str, str] = {}

TEMPLATE = """Hi {first}, thank you for choosing AT&T! Here's your order wrap-up — your sales rep {rep} and your VIP Support Manager Taylor are both in this thread for anything you need.

• Order # {order}
• BAN # {ban}
• 4 Digit PIN # — {pin}
• Track Order: att.com/orders/checkmyorder
• Activate Phones: att.com/activations/activatewireless
• Trade-In: nextqr.com/tradein-nds
• Taylor VIP Manager - 945-337-2199
• ATT To-Do List: {todo}"""

PIN_FALLBACK = "your rep will confirm your 4-digit PIN here"
# Taylor's VIP line as the canvas publishes it — the send-from when the API
# can't be asked (no ReadAccounts scope on this app).
TAYLOR_SMS_NUMBER = "945-337-2199"


# --- pieces -------------------------------------------------------------------

def _load_sent() -> Dict[str, dict]:
    try:
        return json.loads(SENT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_sent(state: Dict[str, dict]) -> None:
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _contact_name(c: dict) -> str:
    return " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x)


def _contact_phone(c: dict) -> str:
    for k in ("mobilePhone", "businessPhone", "homePhone", "otherPhone"):
        if c.get(k):
            return str(c[k])
    return ""


def resolve_reps(book: List[dict], rep_names: List[str],
                 log=print) -> Dict[str, str]:
    """{SaraPlus rep spelling: phone} off Taylor's address book — the same
    three-pass unique-hit matcher the roster rides everywhere; an ambiguous
    or missing rep stays unresolved and their customers are SKIPPED."""
    from automations.total_knocks import guests
    from automations.total_knocks.pull import COL_REP

    rows = [{COL_REP: _contact_name(c)} for c in book]
    claimed, missing = guests.match_rows(rows, rep_names)
    out: Dict[str, str] = {}
    for i, rep in claimed.items():
        phone = _contact_phone(book[i])
        if phone:
            out[rep] = phone
        else:
            missing.append(rep)
    for rep, phone in REP_PHONE_OVERRIDES.items():
        out[rep] = phone
    for rep in sorted(set(missing) - set(out)):
        log("  ✗ no number for rep %r in the contact list — their "
            "customers will be skipped" % rep)
    return out


def guest_fields(since: dt.date, until: dt.date, log=print) -> List[Dict]:
    """The guest customers plus the flyer's fill-ins (order #, BAN) straight
    off the envelope's raw rows."""
    import base64
    import csv
    import io

    from automations.rc_contact_sync import guest
    from automations.sp_order_log import raf_guest

    customers = guest.guest_customers(since, until, log=lambda *a, **k: None)
    env = raf_guest.fetch(log=log)
    raw = {r.get("Order ID", "").strip(): r for r in csv.DictReader(
        io.StringIO(base64.b64decode(env["csv"]).decode("utf-8-sig")))}
    for c in customers:
        r = raw.get(c["order_id"], {})
        c["wireless_order"] = (r.get("Wireless Order #", "") or "").strip()
        c["ban"] = (r.get("Wireless Acct #", "") or "").strip()
    return customers


def build_text(cust: Dict) -> str:
    first = titlecase_name(RC.split_name(cust["customer_name"])[0]) or "there"
    return TEMPLATE.format(
        first=first,
        rep=titlecase_name(cust["rep"]),
        order=cust.get("wireless_order") or "(coming — rep will confirm)",
        ban=cust.get("ban") or "(coming — rep will confirm)",
        pin=PIN_FALLBACK,
        todo=TODO_URL)


def fetch_flyer(file_id: str = FLYER_FILE_ID, log=print) -> int:
    """Download the canvas's flyer image from Slack to FLYER_PATH, with the
    metrics user token (it can read what the user can see; url_private needs
    the same bearer)."""
    import requests as _rq

    from automations.shared import slack_metrics_post as smp

    cli = smp._client()
    info = cli.files_info(file=file_id)
    f = info["file"]
    url = f.get("url_private_download") or f.get("url_private")
    r = _rq.get(url, headers={"Authorization": "Bearer %s" % cli.token},
                timeout=60)
    r.raise_for_status()
    data = r.content
    if not data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"):
        log("downloaded %d bytes but it does not look like an image "
            "(mimetype %r) — NOT saved" % (len(data), f.get("mimetype")))
        return 1
    FLYER_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLYER_PATH.write_bytes(data)
    log("flyer %r (%s, %s bytes) -> %s"
        % (f.get("name"), f.get("mimetype"), "{:,}".format(len(data)),
           FLYER_PATH))
    if len(data) > 1_000_000:
        log("NOTE: over ~1MB — MMS carriers cap near 1.5MB total; if sends "
            "bounce, downscale this file")
    print("=== done ===", flush=True)
    return 0


# --- the run ------------------------------------------------------------------

def run(since: dt.date, until: dt.date, *, live: bool = False,
        find_reps_only: bool = False, limit: Optional[int] = None,
        log=print) -> int:
    log("D2D wrap-up sender — %s..%s%s"
        % (since, until, "" if live else "  (DRY RUN)"))

    customers = guest_fields(since, until, log=log)
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

    msgs = RC.sms_since(watch_token, watch_ext, since)
    missing = [c for c in customers
               if not RC.texted(msgs, c["phone"],
                                [c.get("customer_name", ""),
                                 c.get("business", "")])]
    log("%d customer(s) in window, %d never messaged"
        % (len(customers), len(missing)))

    book = RC.address_book(token, contacts_ext)
    rep_names = sorted({c["rep"] for c in missing})
    reps = resolve_reps(book, rep_names, log=log)
    if find_reps_only:
        for rep, phone in sorted(reps.items()):
            log("  %-28s %s" % (titlecase_name(rep), phone))
        # For every rep the book could NOT answer, show what it holds that
        # shares a name token — the 0-of-21 run (2026-10-08) needs eyes on
        # whether the reps are in there under other spellings or not at all.
        unresolved = [r for r in rep_names if r not in reps]
        if unresolved:
            log("--- near matches for the unresolved (%d contact(s) in "
                "the book) ---" % len(book))
            toks = {w.lower() for r in unresolved for w in r.split()
                    if len(w) >= 4}
            hits = 0
            for c in book:
                name = _contact_name(c)
                if any(t in name.lower() for t in toks):
                    log("  book: %-30s %s" % (name, _contact_phone(c) or
                                              "(no phone)"))
                    hits += 1
                    if hits >= 25:
                        log("  … (capped at 25)")
                        break
            if not hits:
                log("  (nothing in the book shares a name token with them)")
        print("=== done ===", flush=True)
        return 0

    # Asking the API for the line needs the ReadAccounts scope this app
    # doesn't have (CMN-401 on the first live try, 2026-10-08) — so the
    # canvas's published number is the authority and the API is a bonus.
    try:
        from_number = RC.sender_number(token)
    except RC.RCError as e:
        from_number = TAYLOR_SMS_NUMBER
        log("phone-number endpoint unavailable (%s) — using the canvas's %s"
            % (str(e)[:80], from_number))
    log("sending from %s (Taylor's line)" % from_number)

    flyer = None
    for p in (FLYER_PATH, FLYER_REPO_PATH):
        if p.exists():
            flyer = ("wrapup_flyer.png", p.read_bytes(), "image/png")
            log("flyer attached: %s (%s bytes)"
                % (p, "{:,}".format(len(flyer[1]))))
            break
    if flyer is None:
        log("NO FLYER at %s — text goes alone (run --fetch-flyer first)"
            % FLYER_PATH)

    sent_state = _load_sent()
    sent = skipped = failed = 0
    preview: List[str] = []   # dry run: the whole plan, uploaded for the mini
    if limit:
        missing = missing[:limit]
    for cust in missing:
        key = "%s:%s" % (cust["day"], cust["order_id"])
        who = titlecase_name(cust["customer_name"]) or cust["order_id"]
        if key in sent_state:
            log("  – %s: wrap-up already sent %s"
                % (who, sent_state[key].get("at", "")))
            continue
        rep_phone = reps.get(cust["rep"])
        if not rep_phone:
            log("  – %s: rep %r unresolved — SKIPPED"
                % (who, titlecase_name(cust["rep"])))
            skipped += 1
            continue
        text = build_text(cust)
        to = [cust["phone"], rep_phone]
        if not live:
            log("  [dry-run] group: %s (customer) + %s (%s)\n%s\n"
                % (RC.e164(cust["phone"]), RC.e164(rep_phone),
                   titlecase_name(cust["rep"]),
                   "\n".join("      " + ln for ln in text.split("\n"))))
            preview.append("GROUP %s | %s (customer %s) + %s (rep %s)\n%s"
                           % (cust["day"], who, RC.e164(cust["phone"]),
                              RC.e164(rep_phone), titlecase_name(cust["rep"]),
                              text))
            sent += 1
            continue
        try:
            res = RC.send_group_mms(token, from_number, to, text,
                                    attachment=flyer)
            sent_state[key] = {"at": dt.datetime.now().isoformat(
                timespec="seconds"), "to": [RC.e164(n) for n in to],
                "msg_id": res.get("id")}
            _save_sent(sent_state)
            sent += 1
            log("  + %s — group with %s" % (who, titlecase_name(cust["rep"])))
            time.sleep(6)   # polite pacing; RC business SMS is ~40-60/min
        except RC.RCError as e:
            failed += 1
            log("  ✗ %s: %s" % (who, str(e)[:200]))
    log("wrap-ups: %d %s, %d skipped (no rep number), %d failed"
        % (sent, "sent" if live else "previewed", skipped, failed))
    if not live:
        # the full plan, retrievable whole on the mini (the Result cell
        # truncates; this doesn't): sp_order_log's base64-tab relay.
        try:
            from automations.rc_contact_sync.status_probe import _upload_bytes
            head = ("flyer: %s\nfrom: %s\n\n"
                    % ("yes" if flyer else "NO — text only", from_number))
            _upload_bytes((head + "\n\n====\n\n".join(preview)).encode(),
                          "Wrapup Preview", log=log)
        except Exception as e:  # noqa: BLE001
            log("  (preview upload failed: %s: %s)"
                % (type(e).__name__, str(e)[:120]))
    print("=== done ===", flush=True)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_wrapup",
        description="Group-text the D2D wrap-up (Taylor + rep + customer) to "
                    "the guest customers nobody texted.")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="required unless --fetch-flyer")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                    help="default: yesterday")
    ap.add_argument("--live", action="store_true",
                    help="actually send (default: print every message)")
    ap.add_argument("--find-reps", action="store_true",
                    help="only resolve + print the reps' numbers")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N (for a careful first --live)")
    ap.add_argument("--fetch-flyer", action="store_true",
                    help="only download the canvas flyer image to the "
                         "config area, then exit")
    args = ap.parse_args(argv)
    if args.fetch_flyer:
        return fetch_flyer()
    if not args.since:
        print("✗ --since is required (e.g. --since 2026-09-29)")
        return 2
    since = dt.date.fromisoformat(args.since)
    until = (dt.date.fromisoformat(args.until) if args.until
             else C.yesterday())
    return run(since, until, live=args.live, find_reps_only=args.find_reps,
               limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
