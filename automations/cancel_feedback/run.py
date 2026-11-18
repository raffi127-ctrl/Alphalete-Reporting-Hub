"""Cancel/disconnect feedback outreach — daily run.

  python -m automations.cancel_feedback.run                 # DRY RUN, Rafael's office only
  python -m automations.cancel_feedback.run --scope full    # DRY RUN, whole captainship
  python -m automations.cancel_feedback.run --live          # SEND (Rafael's office)
  python -m automations.cancel_feedback.run --scope full --live
  python -m automations.cancel_feedback.run --collect-responses        # read + log replies
  python -m automations.cancel_feedback.run --cancel-csv c.csv --disconnect-csv d.csv  # offline

DRY RUN is the default — it prints exactly who would be texted and the rendered
message, and sends nothing. Preview Rafael Hidalgo's office, then --scope full.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from automations.cancel_feedback import config as C
from automations.cancel_feedback import source
from automations.cancel_feedback import log as flog

REPORT_ID = "cancel_feedback"


def _within_quiet_hours(now: Optional[dt.datetime] = None) -> bool:
    h = (now or dt.datetime.now()).hour
    start, end = C.QUIET_HOURS
    return start <= h < end


def select_recipients(customers: List[dict], texted: set, opted: set
                      ) -> Tuple[List[dict], List[Tuple[dict, str]]]:
    """Split the gathered customers into (to_text, skipped-with-reason),
    honoring the once-per-customer ledger and the opt-out list."""
    to_text: List[dict] = []
    skipped: List[Tuple[dict, str]] = []
    for c in customers:
        if c["phone"] in opted:
            skipped.append((c, "opted-out"))
        elif C.ONE_TEXT_PER_CUSTOMER and c["phone"] in texted:
            skipped.append((c, "already-texted"))
        else:
            to_text.append(c)
    return to_text, skipped


def run(scope: str = "test", day: Optional[dt.date] = None, *, dry_run: bool = True,
        cancel_csv=None, disconnect_csv=None, log=print) -> int:
    day = day or C.yesterday()
    owners = C.owners_for_scope(scope)
    log("Cancel feedback — scope=%s (%d office%s), day=%s%s"
        % (scope, len(owners), "" if len(owners) == 1 else "s", day,
           "  (DRY RUN)" if dry_run else ""))

    customers = source.gather(day, owners=owners, cancel_csv=cancel_csv,
                              disconnect_csv=disconnect_csv, log=log)
    if not customers:
        log("no cancels/disconnects for %s in scope — nothing to do" % day)
        return 0

    texted = flog.already_texted_phones(log=log)
    opted = flog.opted_out_phones(log=log)
    to_text, skipped = select_recipients(customers, texted, opted)
    for c, why in skipped:
        log("  skip %s (%s) — %s" % (c["customer_name"] or c["phone"], c["phone"], why))
    log("would text: %d  (skipped %d)" % (len(to_text), len(skipped)))

    # Live sends only inside quiet hours.
    if not dry_run and not _within_quiet_hours():
        log("outside quiet hours %s — holding all sends this run" % (C.QUIET_HOURS,))
        return 0

    creds = C.rc_creds() if not dry_run else None
    token = None
    if not dry_run:
        from automations.cancel_feedback import ringcentral as rc
        token = rc.get_access_token(creds, log=log)   # ONE token for the whole run
    sent = 0
    failed = 0
    entries: List[Dict] = []
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    try:
        for c in to_text:
            msg = C.render(c["first"])
            if dry_run:
                log("  [dry-run] -> %s  %s  [%s%s]\n      %s"
                    % (c["phone"], c["customer_name"], c["kind"],
                       (" · " + c["reason"]) if c["reason"] else "", msg))
                continue
            ok, mid, _ = rc.send(token, creds["send_from"], c["phone"], msg, log=log)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
            entries.append({"texted_at": now_iso, "customer": c["customer_name"],
                            "phone": c["phone"], "kind": c["kind"], "reason": c["reason"],
                            "rep": c["rep"], "owner": c["owner"],
                            "status": "sent" if ok else "failed", "message_id": mid or ""})
            log("  %s -> %s  %s" % ("sent" if ok else "FAILED", c["phone"], c["customer_name"]))
            time.sleep(1.2)   # gentle spacing: stay under the SMS send rate limit
    finally:
        # Log whatever actually went out, even if the loop raised partway.
        if not dry_run and entries:
            flog.record_outreach(entries, log=log)
            log("sent %d, failed %d, logged %d row(s)" % (sent, failed, len(entries)))

    print("[%s] %s Finished%s" % (REPORT_ID, "⚠" if failed else "✅",
          (" — %d failed" % failed) if failed else ""), flush=True)
    print("=== done ===", flush=True)
    return 1 if failed else 0


def collect_responses(since: Optional[dt.date] = None, *, dry_run: bool = True,
                      log=print) -> int:
    """Read inbound replies, match them to customers we texted, and log the
    feedback (flagging STOP-style opt-outs)."""
    from automations.cancel_feedback import ringcentral as rc
    if not flog.configured():
        log("response collection needs the log sheet wired (LOG_SHEET_ID) — skipped")
        return 0
    since = since or (dt.date.today() - dt.timedelta(days=14))
    creds = C.rc_creds()
    our = flog.outreach_map(log=log)                       # phone -> customer
    already = flog.logged_reply_ids(log=log)
    replies = rc.replies_since(creds, since, log=log)
    new: List[Dict] = []
    for r in replies:
        if r["phone"] not in our or r["id"] in already:
            continue
        new.append({"received_at": r["time"], "phone": r["phone"],
                    "customer": our.get(r["phone"], ""), "feedback": r["text"],
                    "opted_out": rc.is_opt_out(r["text"]), "message_id": r["id"]})
    log("new replies to log: %d" % len(new))
    for e in new:
        tag = "  (OPT-OUT)" if e["opted_out"] else ""
        log("  <- %s  %s%s: %r" % (e["phone"], e["customer"], tag, e["feedback"][:120]))
    if not dry_run:
        flog.record_responses(new, log=log)
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cancel_feedback")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--scope", choices=["test", "full"], default="test",
                    help="test = Rafael Hidalgo's office only (default); full = whole captainship")
    ap.add_argument("--live", action="store_true", help="actually SEND")
    ap.add_argument("--dry-run", action="store_true", help="the default: print, send nothing")
    ap.add_argument("--collect-responses", action="store_true",
                    help="read + log inbound replies instead of sending")
    ap.add_argument("--since", default=None, help="responses: look back from this YYYY-MM-DD")
    ap.add_argument("--cancel-csv", default=None, help="offline: use this cancels crosstab")
    ap.add_argument("--disconnect-csv", default=None, help="offline: use this disconnects crosstab")
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    day = dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    if args.collect_responses:
        since = dt.datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None
        return collect_responses(since, dry_run=not args.live)
    return run(args.scope, day, dry_run=not args.live,
               cancel_csv=args.cancel_csv, disconnect_csv=args.disconnect_csv)


if __name__ == "__main__":
    raise SystemExit(main())
