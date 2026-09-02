"""B2B Customer Contacts — SaraPlus -> RingCentral, + the un-texted alert.

Usage (Lucy 2):
  python -m automations.rc_contact_sync.run --probe      # read-only: what's there
  python -m automations.rc_contact_sync.run              # DRY RUN (default)
  python -m automations.rc_contact_sync.run --live       # create contacts + post
  python -m automations.rc_contact_sync.run 2026-09-01   # a specific day
  python -m automations.rc_contact_sync.run --live --limit 1   # first customer only

DRY RUN IS THE DEFAULT and it is not politeness: a RingCentral contact cannot
be un-created from this API without a second delete call, and a Slack post
naming reps who "never texted the customer" is the kind of message that should
never go out on a guess. Bare runs print exactly what a --live run would do.
The scheduled wrapper is what passes --live.

Exit codes: 0 clean · 1 something failed (Hub card goes red) · 2 bad arguments.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from automations.shared.name_case import titlecase_name
from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC
from automations.rc_contact_sync import sara

REPORT_ID = "rc_contact_sync"
NO_REP = "(no rep on the order)"


# --- the Slack message --------------------------------------------------------

def missing_text_message(day: dt.date, missing: List[Dict[str, str]],
                         total: int) -> str:
    """One post naming the customers nobody texted, grouped by rep — the rep
    is the person who has to do something about it, so the rep is the heading
    rather than a column somebody has to scan for their own name."""
    # Built by hand, not with %-d: that flag is a no-op on Windows and every
    # report here has to run on both. [[feedback_cross_platform_reports]]
    head = "%s — %s %d, %d" % (C.SLACK_HEADER, day.strftime("%B"),
                               day.day, day.year)
    if not missing:
        return ("%s\nAll %d customer%s from yesterday were texted. :white_check_mark:"
                % (head, total, "" if total == 1 else "s"))
    by_rep: Dict[str, List[Dict[str, str]]] = {}
    for m in missing:
        # An order with no rep on it is still somebody's customer — it gets its
        # own heading rather than being dropped or filed under a guess.
        by_rep.setdefault(titlecase_name(m.get("rep", "")) or NO_REP,
                          []).append(m)
    lines = ["%s\n%d of %d customer%s from yesterday %s no text on %s's line:"
             % (head, len(missing), total, "" if total == 1 else "s",
                "has" if len(missing) == 1 else "have",
                C.WATCH_OWNER_NAME.split()[0])]
    for rep in sorted(by_rep):
        lines.append("*%s*" % rep)
        for m in by_rep[rep]:
            who = titlecase_name(m.get("business", "")) or \
                  titlecase_name(m.get("customer_name", "")) or "(no name)"
            extra = titlecase_name(m.get("customer_name", ""))
            tail = " — %s" % extra if extra and extra != who else ""
            lines.append("  • %s%s — %s" % (who, tail,
                                            m.get("phone") or "no phone on file"))
    return "\n".join(lines)


def post_missing(day: dt.date, missing: List[Dict[str, str]], total: int,
                 *, dry_run: bool, log=print) -> List[str]:
    """Post into today's metrics thread in BOTH of Carlos's channels.

    A channel that has no metrics thread yet is reported and skipped, not
    retried into the channel top level: an alert that lands outside the thread
    reads as a different report and gets ignored."""
    from automations.shared import slack_metrics_post as smp

    text = missing_text_message(day, missing, total)
    failed: List[str] = []
    for chan in C.CHANNELS:
        label = C.CHANNEL_LABEL.get(chan, chan)
        if dry_run:
            log("  [dry-run] would post to %s:\n%s" % (label, text))
            continue
        try:
            res = smp.post_reply_text_only(text, channel_id=chan)
            log("  posted to %s (ts=%s)" % (label, res.get("ts")))
        except Exception as e:                             # noqa: BLE001
            log("  ✗ %s: %s: %s" % (label, type(e).__name__, str(e)[:200]))
            failed.append(label)
    return failed


# --- the run ------------------------------------------------------------------

def run(day: Optional[dt.date] = None, *, dry_run: bool = True,
        limit: Optional[int] = None, headless: bool = True,
        skip_slack: bool = False, log=print) -> int:
    day = day or C.yesterday()
    log("B2B Customer Contacts — %s%s" % (day, "  (DRY RUN)" if dry_run else ""))

    # 1. SaraPlus. Carlos's login only.
    customers = sara.scrape(day, headless=headless, limit=limit, log=log)
    if not customers:
        log("No orders on %s — nothing to add, nothing to chase." % day)
        _manifest([], dry_run=dry_run, note="no orders on %s" % day)
        return 0

    # 2. RingCentral: who am I, and is it the right person? A wrong-but-valid
    #    token writes into the wrong address book and reads the wrong inbox,
    #    and the run still looks green -- so this stops before any write.
    creds = C.rc_creds()
    token = RC.token(creds)
    me = RC.identity(token)
    log("RingCentral: %s <%s> (ext %s, account %s)"
        % (me["name"] or "?", me["email"] or "no email",
           me["extension_number"], me["account_id"]))
    RC.assert_identity(me, creds.get("expected_email", ""))
    contacts_ext = str(creds["contacts_extension_id"])
    watch_ext = str(creds["watch_extension_id"])

    # 3. Contacts — indexed by phone first, so a re-run adds nothing twice.
    book = RC.address_book(token, contacts_ext)
    by_phone = RC.index_by_phone(book)
    log("address book: %d existing contact(s)" % len(book))
    state = C.prune_state(C.load_state())

    added, skipped, failed_rows = [], [], []
    for cust in customers:
        key = "%s:%s" % (cust["day"], cust["order_id"])
        phone = RC.norm_phone(cust["phone"])
        label = cust.get("business") or cust.get("customer_name") or cust["order_id"]
        if not phone:
            log("  – %s: no primary phone on the customer card — skipped" % label)
            failed_rows.append(label)
            continue
        if key in state:
            skipped.append(label)
            log("  – %s: already added on a previous run" % label)
            continue
        if phone in by_phone:
            skipped.append(label)
            state[key] = {"day": cust["day"], "phone": phone,
                          "existing": True}
            log("  – %s: %s already in the address book" % (label, cust["phone"]))
            continue
        first, last = RC.split_name(cust["customer_name"])
        notes = "Rep Name: %s" % titlecase_name(cust["rep"])
        if dry_run:
            log("  [dry-run] would create: company=%r name=%r phone=%s notes=%r"
                % (titlecase_name(cust["business"]), ("%s %s" % (first, last)).strip(),
                   RC.e164(cust["phone"]), notes))
            added.append(label)
            continue
        try:
            RC.create_contact(token, contacts_ext, first=first, last=last,
                              company=titlecase_name(cust["business"]), phone=cust["phone"],
                              notes=notes)
        except RC.RCError as e:
            log("  ✗ %s: %s" % (label, str(e)[:200]))
            failed_rows.append(label)
            continue
        # Written per contact, not at the end: a crash halfway through must not
        # re-create everything that already landed.
        state[key] = {"day": cust["day"], "phone": phone, "existing": False}
        C.save_state(state)
        by_phone[phone] = {"company": cust["business"]}
        added.append(label)
        log("  + %s — %s (Rep: %s)" % (titlecase_name(cust["business"]) or first,
                                       RC.e164(cust["phone"]),
                                       titlecase_name(cust["rep"])))
    if not dry_run:
        C.save_state(state)
    log("contacts: %d added, %d already there, %d could not be added"
        % (len(added), len(skipped), len(failed_rows)))

    # 4. Did anyone text them on Taylor's line?
    # Same token, same person: we are signed in as the line being watched.
    # watch_jwt only exists for the day those two stop being the same.
    watch_token = token
    if creds.get("watch_jwt"):
        watch_token = RC.token(creds, jwt=creds["watch_jwt"])
    msgs = RC.sms_for_day(watch_token, watch_ext, day)
    log("%s's line: %d SMS on %s" % (C.WATCH_OWNER_NAME, len(msgs), day))
    missing = [c for c in customers
               if not RC.texted(msgs, c["phone"],
                                [c.get("customer_name", ""), c.get("business", "")])]
    log("un-texted: %d of %d" % (len(missing), len(customers)))

    slack_failed: List[str] = []
    if skip_slack:
        log("--no-slack: skipping the post")
    else:
        slack_failed = post_missing(day, missing, len(customers),
                                    dry_run=dry_run, log=log)

    failed = failed_rows + slack_failed
    _manifest(failed, dry_run=dry_run,
              note="%d customers, %d contacts added, %d un-texted"
                   % (len(customers), len(added), len(missing)))
    print("[rc_contact_sync] %s Finished%s"
          % ("⚠" if failed else "✅",
             (" — failed: %s" % ", ".join(failed)) if failed else ""), flush=True)
    print("=== done ===", flush=True)
    return 1 if failed else 0


def _manifest(failed: List[str], *, dry_run: bool, note: str = "") -> None:
    """Publish the run to the Hub. A LaunchAgent report that doesn't publish is
    a report nobody can see fail. [[feedback_launchd_reports_must_publish]]"""
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, failed=failed, kind="part", note=note,
                           dry_run=dry_run)
    except Exception as e:                                 # noqa: BLE001
        print("  (manifest not written: %s: %s)" % (type(e).__name__, str(e)[:120]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_contact_sync",
        description="SaraPlus B2B customers -> RingCentral contacts, and a "
                    "Slack alert for the ones nobody texted.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--live", action="store_true",
                    help="create the contacts and POST to Slack for real")
    ap.add_argument("--dry-run", action="store_true",
                    help="the default: print what a --live run would do")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: dump what SaraPlus actually shows "
                         "(tabs, date fields, grid headers, first customer "
                         "card). Run this first on a new machine.")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N orders (for a careful first --live)")
    ap.add_argument("--no-slack", action="store_true",
                    help="do everything except the Slack post")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (debugging)")
    args = ap.parse_args(argv)

    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else None)
    if args.probe:
        sara.probe(day, headless=not args.headed)
        return 0
    return run(day, dry_run=not args.live, limit=args.limit,
               headless=not args.headed, skip_slack=args.no_slack)


if __name__ == "__main__":
    raise SystemExit(main())
