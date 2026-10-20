"""Raf's office wrap-up check — SaraPlus (all reps) x Dylan's RingCentral line,
then the "nobody texted them" post to #alphalete-sales.

Usage:
  python -m automations.rc_contact_sync_raf.run --probe   # read-only: identity + counts
  python -m automations.rc_contact_sync_raf.run           # DRY RUN (default): prints the post
  python -m automations.rc_contact_sync_raf.run --live    # post to Slack for real
  python -m automations.rc_contact_sync_raf.run 2026-10-19        # a specific day
  python -m automations.rc_contact_sync_raf.run --since 2026-10-13  # backfill a range

DRY RUN IS THE DEFAULT: a Slack post naming reps who "never texted the
customer" should never go out on a guess, so a bare run prints exactly what a
--live run would post. The scheduled wrapper passes --live.

There is NO contacts step. Dylan's RingCentral app can read messages
(ReadMessages) but not contacts (no ReadContacts scope), so this report does
the wrap-up check and the Slack post only. See the package docstring.

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
from automations.rc_contact_sync_raf import config as C
from automations.rc_contact_sync_raf import customers as cust
from automations.rc_contact_sync import ringcentral as RC

REPORT_ID = "rc_contact_sync_raf"
NO_REP = "(no rep on the order)"


def missing_names_reply(missing: List[Dict[str, str]], total: int) -> str:
    """The threaded reply: the un-texted customers, grouped by the rep who
    sold them, each with their phone and their product categories.

    Based on rc_contact_sync.run.missing_names_reply (grouped by rep, bold
    name headers), extended per Dylan 2026-10-20 to carry the customer's phone
    + products (Internet / TV / Wireless) and, at the BOTTOM, to @MENTION every
    rep in one line. The rep→Slack-id resolution is the universal shared store
    (slack_tag_learning), which is spelling-safe: a rep not in the store is
    simply not mentioned (never a guessed @mention — the whole reason Carlos's
    B2B version tags nobody) and is listed so a human can add them once.
    'Jordan Ruiz' never resolves to 'Analay Ruiz'."""
    from automations.shared import slack_tag_learning as tags

    if not missing:
        return ("The 1 customer was messaged. :white_check_mark:" if total == 1
                else "All %d customers were messaged. :white_check_mark:" % total)
    by_rep: Dict[str, List[Dict[str, str]]] = {}
    for m in missing:
        by_rep.setdefault(titlecase_name(m.get("rep", "")) or NO_REP,
                          []).append(m)
    lines = ["%d of %d customer%s never got a message:"
             % (len(missing), total, "" if total == 1 else "s")]
    mentions: List[str] = []
    untagged: List[str] = []
    for rep in sorted(by_rep):
        lines.append("*%s*" % rep)   # original look: a bold name header
        for m in by_rep[rep]:
            who = titlecase_name(m.get("business", "")) or \
                  titlecase_name(m.get("customer_name", "")) or "(no name)"
            extra = titlecase_name(m.get("customer_name", ""))
            tail = " — %s" % extra if extra and extra != who else ""
            phone = m.get("phone") or "no phone on file"
            prods = ", ".join(m.get("products") or []) or "no product on file"
            lines.append("  • %s%s — %s — %s" % (who, tail, phone, prods))
        if rep != NO_REP:
            sid = tags.lookup(rep)
            (mentions.append("<@%s>" % sid) if sid else untagged.append(rep))
    # Everybody, tagged once, at the very bottom.
    if mentions:
        lines.append("")
        lines.append(" ".join(mentions))
    if untagged:
        lines.append(":warning: No Slack match to tag: %s — add them to "
                     "automations/shared/slack_known_users.json and they'll "
                     "tag next run." % ", ".join(untagged))
    return "\n".join(lines)


def missing_rep_lines(missing: List[Dict[str, str]]) -> List[str]:
    """The PARENT post's body: just the reps who have an un-texted customer,
    one per line (Dylan 2026-10-20 — the header lists the reps, the per-customer
    detail goes in the threaded reply). Plain names, not @mentions; the tags
    live at the bottom of the reply."""
    reps = sorted({titlecase_name(m.get("rep", "")) or NO_REP for m in missing})
    return ["• %s" % r for r in reps]


class IdentityError(RuntimeError):
    pass


# --- RingCentral identity -----------------------------------------------------

def _token_and_identity(log=print):
    """Mint Dylan's token and prove it is his extension before anything posts.

    A valid JWT for any other RingCentral user would read the wrong inbox and
    name the wrong reps in Slack — a run that looks green. So owner_id is
    checked against the one baked into rc_autoread, and a ReadMessages scope is
    required (without it sms_since reads nothing, which reads as 'nobody texted
    anyone' and would chase every rep)."""
    creds = C.rc_creds()
    info = RC.token_info(creds)
    me = RC.identity(info)
    log("RingCentral: extension id %s, scope [%s]"
        % (me["owner_id"], me["scope"]))
    want = creds["expected_owner_id"]
    if me.get("owner_id") != want:
        raise IdentityError(
            "this RingCentral token belongs to extension id %s, not %s "
            "(Dylan's). The wrong inbox would be read and the wrong reps named "
            "in #alphalete-sales. Mint the JWT on Dylan's login, or fix "
            "EXPECTED_OWNER_ID in rc_contact_sync_raf/config.py if the "
            "extension really did change."
            % (me.get("owner_id") or "unknown", want))
    if "ReadMessages" not in (me.get("scope") or ""):
        raise IdentityError(
            "this RingCentral token is missing the ReadMessages scope (has "
            "[%s]). Without it the message store reads empty, which would make "
            "every customer look un-texted and chase every rep. Add "
            "ReadMessages to the app and re-mint the JWT." % me.get("scope"))
    return info["access_token"], me


# --- the Slack post -----------------------------------------------------------

def post_missing(day: dt.date, missing: List[Dict[str, str]], total: int,
                 *, dry_run: bool, prefix: str = "", log=print) -> List[str]:
    """Header post + the names as a reply IN ITS THREAD, in #alphalete-sales.
    Mirrors rc_contact_sync.run.post_missing; a same-day rerun replies under
    the morning's header (saved_thread_ts) instead of opening a second one."""
    from automations.shared import slack_metrics_post as smp

    title = C.SLACK_HEADER
    rep_lines = missing_rep_lines(missing)   # the parent post's body
    body = missing_names_reply(missing, total)
    if prefix:
        body = prefix + "\n" + body
    failed: List[str] = []
    for chan in C.CHANNELS:
        label = C.CHANNEL_LABEL.get(chan, chan)
        if dry_run:
            head_preview = "\n".join(["    header: %s — %s" % (title, day)]
                                     + ["      " + ln for ln in rep_lines])
            log("  [dry-run] would post to %s:\n%s\n    reply:\n%s"
                % (label, head_preview, "\n".join("      " + ln
                                                  for ln in body.split("\n"))))
            continue
        try:
            ts = C.saved_thread_ts(day, chan)
            existed = bool(ts)
            if not ts:
                head = smp.ensure_named_thread(title, day, lines=rep_lines,
                                               channel_id=chan)
                ts = head.get("thread_ts")
                if not ts:
                    raise RuntimeError("no thread_ts came back: %s" % head)
                C.save_thread_ts(day, chan, ts)
            res = smp.post_reply_text_only(body, thread_ts=ts, channel_id=chan)
            log("  posted to %s (%s header, reply ts=%s)"
                % (label, "existing" if existed else "new", res.get("ts")))
        except Exception as e:                             # noqa: BLE001
            log("  ✗ %s: %s: %s" % (label, type(e).__name__, str(e)[:200]))
            failed.append(label)
    return failed


# --- the run ------------------------------------------------------------------

def run(day: Optional[dt.date] = None, *, dry_run: bool = True,
        skip_slack: bool = False, since: Optional[dt.date] = None,
        prefix: str = "", log=print) -> int:
    day = day or C.yesterday()
    window_start = since or day
    log("Raf wrap-up check — %s%s%s"
        % (day, "" if window_start == day else "  (from %s)" % window_start,
           "  (DRY RUN)" if dry_run else ""))

    # 1. Raf's orders (all reps) off the Lucy 1 handoff. A missing/stale pull
    #    is a hard fail here — an empty list would read as "everyone texted".
    try:
        customers = cust.all_customers(window_start, day, log=log)
    except Exception as e:                                 # noqa: BLE001
        log("✗ could not load Raf's orders: %s: %s" % (type(e).__name__, e))
        _manifest(["raf orders: %s" % type(e).__name__], dry_run=dry_run,
                  note=str(e)[:160])
        return 1
    if not customers:
        log("No orders under Raf's code on %s — nothing to check." % day)
        _manifest([], dry_run=dry_run, note="no orders on %s" % day)
        return 0

    # 2. RingCentral: who am I, and is it Dylan? Stop before posting if not.
    try:
        token, _me = _token_and_identity(log=log)
    except (IdentityError, RC.RCError) as e:
        log("✗ RingCentral identity: %s" % e)
        _manifest(["ringcentral identity"], dry_run=dry_run, note=str(e)[:160])
        return 1

    # 3. Was each customer ever messaged on Dylan's line? sms_since opens at the
    #    sale day and runs to now (a next-morning wrap-up still counts).
    try:
        msgs = RC.sms_since(token, C.WATCH_EXTENSION_ID, window_start)
    except RC.RCError as e:
        log("✗ reading %s: %s" % (C.WATCH_LINE_LABEL, e))
        _manifest(["ringcentral messages"], dry_run=dry_run, note=str(e)[:160])
        return 1
    log("%s: %d SMS since %s" % (C.WATCH_LINE_LABEL, len(msgs), window_start))

    missing = [c for c in customers
               if not RC.texted_any(
                   msgs,
                   [c["phone"]] + list(c.get("alt_phones") or []),
                   [c.get("customer_name", ""), c.get("business", "")],
                   [c.get("wireless_order", ""), c.get("ban", "")])]
    log("never messaged: %d of %d" % (len(missing), len(customers)))

    # 4. Post.
    slack_failed: List[str] = []
    if skip_slack:
        log("--no-slack: skipping the post")
    else:
        slack_failed = post_missing(day, missing, len(customers),
                                    dry_run=dry_run, prefix=prefix, log=log)

    _manifest(slack_failed, dry_run=dry_run,
              note="%d customers, %d never messaged"
                   % (len(customers), len(missing)))
    print("[%s] %s Finished%s"
          % (REPORT_ID, "⚠" if slack_failed else "✅",
             (" — failed: %s" % ", ".join(slack_failed)) if slack_failed
             else ""), flush=True)
    print("=== done ===", flush=True)
    return 1 if slack_failed else 0


def _manifest(failed: List[str], *, dry_run: bool, note: str = "") -> None:
    """Publish the run to the Hub so a scheduled failure is visible."""
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, failed=failed, kind="part", note=note,
                           dry_run=dry_run)
    except Exception as e:                                 # noqa: BLE001
        print("  (manifest not written: %s: %s)"
              % (type(e).__name__, str(e)[:120]))


def probe(day: Optional[dt.date] = None, log=print) -> int:
    """READ-ONLY: prove identity + show the counts without posting."""
    day = day or C.yesterday()
    try:
        token, me = _token_and_identity(log=log)
    except (IdentityError, RC.RCError) as e:
        log("identity: %s" % e)
        return 1
    log("identity OK — Dylan's extension %s" % me["owner_id"])
    try:
        customers = cust.all_customers(day, day, log=log)
    except Exception as e:                                 # noqa: BLE001
        log("orders: %s: %s" % (type(e).__name__, e))
        customers = []
    msgs = RC.sms_since(token, C.WATCH_EXTENSION_ID, day)
    log("%s: %d SMS since %s" % (C.WATCH_LINE_LABEL, len(msgs), day))
    if customers:
        missing = [c for c in customers
                   if not RC.texted_any(msgs, [c["phone"]],
                                        [c.get("customer_name", ""),
                                         c.get("business", "")])]
        log("would flag %d of %d customer(s) as un-texted" %
            (len(missing), len(customers)))
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_contact_sync_raf",
        description="Raf's office wrap-up check: SaraPlus (all reps) x Dylan's "
                    "RingCentral line, posted to #alphalete-sales.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--live", action="store_true",
                    help="POST to Slack for real")
    ap.add_argument("--dry-run", action="store_true",
                    help="the default: print what a --live run would post")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: prove identity + show counts, no post")
    ap.add_argument("--no-slack", action="store_true",
                    help="do the check but skip the Slack post")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="widen the order window back to this date (backfill): "
                         "one post covering the whole range")
    args = ap.parse_args(argv)

    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else None)
    if args.probe:
        return probe(day)
    since = (dt.datetime.strptime(args.since, "%Y-%m-%d").date()
             if args.since else None)
    prefix = ""
    if since:
        until = day or C.yesterday()
        if since > until:
            print("✗ --since %s is after %s." % (since, until))
            return 2
        prefix = ("Sales under Raf's code, %d/%d – %d/%d:"
                  % (since.month, since.day, until.month, until.day))
    return run(day, dry_run=not args.live, skip_slack=args.no_slack,
               since=since, prefix=prefix)


if __name__ == "__main__":
    raise SystemExit(main())
