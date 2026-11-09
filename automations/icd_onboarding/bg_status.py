"""BG Status on the ICD boards, from the ICDs' forwarded Sterling mail.

Megan, 2026-11-09: "we're building it out where all the ICDs are going to
forward these emails to lucysterlingreports@gmail.com."

A dedicated inbox, and that is the part that matters. Every ICD's Sterling
result carries a real person's background-check outcome; `sterling_forward`
deliberately keeps those OUT of the main reporting inbox and alarms if they
start arriving (`code_answer.check_forward_scope`). Sending them somewhere of
their own keeps that rule intact instead of quietly widening a filter.

Nothing about reading or parsing the mail is new: `bg_check_sync` has done it
for Alphalete for months, including the compliance rule that NOBODY is marked
Passed without an explicit "Score PASS" email. This points the same reader at
the new inbox and puts the answer on the right office's board.

WHICH OFFICE A RESULT BELONGS TO. The email does not say — it is one ICD's
forward among many. So the BOARD decides: a person is on exactly one office's
week. Somebody who appears on two boards is REPORTED and ticked on neither,
the same rule the OwnerVille sweep's `match` uses — ambiguous is never guessed,
because the cost of guessing is a background check recorded against the wrong
person at the wrong office.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from automations.icd_onboarding import board as B

# The inbox the ICDs forward to. Theirs alone — see the note above.
INBOX = os.environ.get("ICD_STERLING_INBOX", "lucysterlingreports@gmail.com")

# Only a finished check ticks the box. "Sent" and "Taken, pending" mean the
# check is in flight, and ticking those would read as done on the board and on
# the printed sheet. `bg_check_sync.parse` ranks them; these are the ones that
# mean there is an answer.
DONE_STATUSES = ("Passed", "Failed", "Unperformable", "Complete")


def events(since_days: int = 30, verbose: bool = True) -> List:
    """Parsed Sterling events from the ICDs' inbox.

    Reuses bg_check_sync's reader wholesale — the parsing, the compliance rule
    about never inferring a pass, and the de-duplication are all its.
    """
    from automations.bg_check_sync import email_source

    before = os.environ.get("BGSYNC_IMAP_ACCOUNT")
    os.environ["BGSYNC_IMAP_ACCOUNT"] = INBOX
    try:
        import importlib
        importlib.reload(email_source)
        return email_source.fetch_events(since_days=since_days, verbose=verbose)
    finally:
        if before is None:
            os.environ.pop("BGSYNC_IMAP_ACCOUNT", None)
        else:
            os.environ["BGSYNC_IMAP_ACCOUNT"] = before


def _name_of(ev) -> str:
    return ("%s %s" % (getattr(ev, "first", ""), getattr(ev, "last", ""))).strip()


def route(events_in: Iterable, boards: Dict[str, List[Dict]]) -> Tuple[Dict, List]:
    """({office: {name: status}}, [ambiguous]) — who each result belongs to.

    `boards` is {office key: that week's rows}. A name on exactly one office's
    board is routed there. On two or more it is reported and routed NOWHERE:
    a background check recorded against the wrong person at the wrong office is
    worse than one that needs a human to place.
    """
    where: Dict[str, List[str]] = {}
    for office, rows in (boards or {}).items():
        for r in rows:
            key = B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
            if key:
                where.setdefault(key, []).append(office)

    out: Dict[str, Dict[str, str]] = {}
    ambiguous: List[dict] = []
    for ev in events_in or ():
        status = str(getattr(ev, "status", "") or "")
        if status not in DONE_STATUSES:
            continue                       # still in flight — not an answer yet
        name = _name_of(ev)
        offices = where.get(B._fold(name.replace(" ", "")), [])
        if len(offices) == 1:
            out.setdefault(offices[0], {})[name] = status
        elif len(offices) > 1:
            ambiguous.append({"name": name, "offices": sorted(set(offices)),
                              "status": status})
    return out, ambiguous


def run(week_start: Optional[dt.date] = None, *, offices: Sequence[str] = (),
        since_days: int = 30, dry_run: bool = True, log=print) -> int:
    """Read the inbox and tick BG Status on each office's board.

    DRY BY DEFAULT. Ticks only a finished check, only where the person is on
    exactly one board, and never un-ticks.
    """
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    week = week_start or dt.date.today()
    got = events(since_days=since_days, verbose=False)
    log("%s: %d Sterling event(s) in the last %d days"
        % (INBOX, len(got), since_days))

    boards: Dict[str, List[Dict]] = {}
    books = {}
    for office in offices:
        try:
            book = F.workbook_for(office)
        except RuntimeError as e:
            log("  %s: %s" % (office, e))
            continue
        ws = S.open_board(book, create=False)
        if ws is None:
            log("  %s: no board yet" % office)
            continue
        books[office] = book
        boards[office] = B.for_week(S.rows_of(ws.get_all_values()), week)

    routed, ambiguous = route(got, boards)
    for a in ambiguous:
        log("  ⚠️  %s is on %d boards (%s) — not ticked anywhere"
            % (a["name"], len(a["offices"]), ", ".join(a["offices"])))

    total = 0
    for office, people in routed.items():
        log("  %s: %d finished check(s)" % (office, len(people)))
        total += F.apply(books[office], week, "sterling",
                         {n: {"BG Status": True} for n in people},
                         dry_run=dry_run, log=log)
    if not routed:
        log("  nothing to tick")
    return total


def main(argv=None) -> int:
    """    python -m automations.icd_onboarding.bg_status --office raf
        python -m automations.icd_onboarding.bg_status --office raf --write
    """
    import argparse
    ap = argparse.ArgumentParser(description="BG Status onto the ICD boards.")
    ap.add_argument("--office", action="append", default=[],
                    help="office key; repeatable")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week")
    ap.add_argument("--since-days", type=int, default=30)
    ap.add_argument("--write", action="store_true",
                    help="actually tick (default is a dry run)")
    a = ap.parse_args(argv)
    week = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    run(week, offices=a.office, since_days=a.since_days, dry_run=not a.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
