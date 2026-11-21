"""The two Blue Ink chases: the day before a start, and the morning of it.

Megan's wording on the card: "Then two reminders, to whoever is still
outstanding -- the day before ('if you haven't done this, please do it before
tomorrow') and the morning of (last call before they walk in). Only ever to
the ones who haven't done it, never to somebody who already signed."

WHY THIS COULD NOT BE BUILT BEFORE. Our client could only CREATE a bundle,
and a Blue Ink bundle launches the moment it is created -- so "they have not
signed" would have meant mailing a second contract packet, the exact thing
the double-send guard exists to stop. Probed on 2026-11-20:

    OPTIONS /bundles/<id>/remind/   -> 404, no such route
    OPTIONS /packets/<key>/remind/  -> 200, allow='PUT, OPTIONS'

So the remind is on the PACKET. It re-sends the invitation for the packet
already out: same bundle, same link, nothing duplicated.

WHO GETS ONE. Off the ledger, which is the only record of what we actually
sent, crossed with what Blue Ink says the packet's state is NOW. Three gates,
and all three have to pass:

  * the ledger says we sent them a bundle;
  * Blue Ink says that signer's packet is still unsigned, asked per PACKET
    and not per bundle -- a bundle reads "started" the moment one of several
    signers finishes, which would silence the chase for the others;
  * today is their day-before or their start day, off THEIR start date.

NEVER TWICE ON THE SAME DAY. A reminder is an email to a real person on their
first morning; two of them is worse than none. The ledger carries the stamp.

The send lead itself is `config.SEND_LEAD_DAYS` (2 days), and that is what
makes a chase possible at all -- with a same-day send there is no gap to
chase in.

    python -m automations.blueink_docs.chase                  # dry
    python -m automations.blueink_docs.chase --send
    python -m automations.blueink_docs.chase --date 2026-11-24
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# Which chase a day is, for the ledger note and the log.
DAY_BEFORE = "day-before"
MORNING_OF = "morning-of"


def log(msg: str) -> None:
    print(msg, flush=True)


def due_kind(start: dt.date, today: dt.date) -> Optional[str]:
    """Which chase today is for somebody starting on `start`, or None.

    Only the two days Megan named. NOT "any day before": a packet outstanding
    for a week would otherwise be chased every morning, which trains people
    to ignore the mail that matters on the last one.
    """
    if not start:
        return None
    gap = (start - today).days
    if gap == 1:
        return DAY_BEFORE
    if gap == 0:
        return MORNING_OF
    return None


def note_for(kind: str, start: dt.date) -> str:
    return "%s reminder for %s" % (kind, start.strftime("%m/%d/%Y"))


def already_chased(rows: List[list], email: str, kind: str,
                   start: dt.date) -> bool:
    """Has this exact chase already gone out?

    Keyed on the person, the chase AND the start date, so somebody whose
    start moves gets the new day's reminders while never getting the old
    day's twice.
    """
    want = note_for(kind, start)
    who = str(email or "").strip().lower()
    if not who:
        return False
    for r in rows:
        row = list(r) + [""] * 8
        if str(row[3]).strip().lower() != who:
            continue
        if str(row[7]).strip() == want:
            return True
    return False


def plan(people, sent_rows: List[list], starts: Dict[str, dt.date],
         today: dt.date) -> List[Tuple[object, str, str, dt.date]]:
    """[(person, bundle_id, kind, start)] for everybody owed a chase today.

    Pure: the Blue Ink lookup of whether they have signed happens in `run`,
    against this list, so the decision of WHO is testable without the API.
    """
    by_email: Dict[str, str] = {}
    for r in sent_rows:
        row = list(r) + [""] * 8
        email = str(row[3]).strip().lower()
        bundle = str(row[4]).strip()
        if email and bundle:
            by_email.setdefault(email, bundle)   # the first send is the one

    out = []
    for p in people:
        email = str(getattr(p, "email", "") or "").strip().lower()
        if not email:
            continue
        bundle = by_email.get(email)
        if not bundle:
            continue                       # never sent: nothing to remind of
        start = starts.get(email)
        kind = due_kind(start, today) if start else None
        if not kind:
            continue
        if already_chased(sent_rows, email, kind, start):
            continue
        out.append((p, bundle, kind, start))
    return out


def run(workbook, people, starts: Dict[str, dt.date], *, today: dt.date,
        send: bool = False, log=log) -> int:
    """Chase everybody due today. Returns how many reminders went (or would)."""
    from automations.blueink_docs import blueink as BI
    from automations.blueink_docs import ledger

    rows = ledger.read(workbook)
    due = plan(people, rows, starts, today)
    if not due:
        log("  no Blue Ink chases due %s" % today.strftime("%m/%d/%Y"))
        return 0

    log("  %d possible chase(s) for %s" % (len(due), today.strftime("%m/%d/%Y")))
    went = 0
    writer = ledger.Writer(workbook) if send else None
    for person, bundle, kind, start in due:
        name = ("%s %s" % (getattr(person, "first", ""),
                           getattr(person, "last", ""))).strip()
        # ASKED PER PACKET, AT THE MOMENT OF SENDING. The ledger says what we
        # sent; only Blue Ink knows whether they have signed since, and a
        # reminder to somebody who already did is the one thing this must
        # never do.
        try:
            open_packets = BI.unsigned_packets(bundle)
        except Exception as e:                           # noqa: BLE001
            log("    %-28s SKIPPED — Blue Ink would not say (%s)"
                % (name, type(e).__name__))
            continue
        mine = [q for q in open_packets
                if str(q.get("email", "")).strip().lower()
                == str(person.email).strip().lower()]
        if not mine:
            log("    %-28s already signed — no reminder" % name)
            continue
        key = str(mine[0].get("key") or mine[0].get("id") or "")
        if not key:
            log("    %-28s SKIPPED — packet has no key" % name)
            continue
        if not send:
            log("    %-28s would remind (%s, starts %s)"
                % (name, kind, start.strftime("%m/%d")))
            went += 1
            continue
        try:
            BI.remind_packet(key)
        except Exception as e:                           # noqa: BLE001
            log("    %-28s FAILED — %s: %s" % (name, type(e).__name__,
                                               str(e)[:90]))
            continue
        log("    %-28s reminded (%s)" % (name, kind))
        writer.add(ledger.row_for(person, bundle, "reminded",
                                  note_for(kind, start)))
        went += 1
    if writer is not None:
        # `finish`, not `flush`: it makes a last attempt and hands back by
        # NAME whatever still would not write. The reminder has already gone
        # by then, so an unlogged one is a lost log line, not a lost send --
        # but it is also how somebody gets chased twice tomorrow, so it has
        # to be said out loud rather than swallowed.
        left = writer.finish()
        if left:
            log("  NOT LOGGED (may be chased again): %s" % ", ".join(left))
    log("  %d reminder(s)%s" % (went, "" if send else "  (dry run)"))
    return went


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--send", action="store_true",
                    help="actually remind (default is a dry run)")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()

    from automations.blueink_docs import config
    from automations.blueink_docs.roster import (attach_chart_dates,
                                                  parse_tab)
    from automations.blueink_docs.run import current_tab
    from automations.recruiting_report.fill import open_by_key

    log("=== Blue Ink chases · %s · %s ==="
        % (today.strftime("%m/%d/%Y"), "SEND" if a.send else "DRY-RUN"))
    workbook = open_by_key(config.SHEET_ID)
    ws = current_tab(workbook, "")
    raw = ws.get_all_values()
    people = parse_tab(raw, ws.title)
    attach_chart_dates(raw, people, ws.title)
    # `chart_date` -- the date on the chart the person actually sits in, which
    # is what `attach_chart_dates` sets. Their OWN start day, not the tab's:
    # one tab carries several charts and a midweek start is a different day
    # from the Monday one, which is the whole reason the chase is per person.
    starts = {}
    for p in people:
        when = getattr(p, "chart_date", None)
        if when and getattr(p, "email", ""):
            starts[str(p.email).strip().lower()] = when
    log("  tab %r: %d person/people, %d with a start date"
        % (ws.title, len(people), len(starts)))
    run(workbook, people, starts, today=today, send=a.send)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
