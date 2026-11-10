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

WHICH OFFICE A RESULT BELONGS TO — the address that forwarded it. Megan,
2026-11-09: "we're able to tell which office the BG is for based on the email
forwarding it? the installer should log that." It already does: setting up an
ICD's Sterling forward writes their address onto the **Sterling Code Mail** tab
(`Office | Forwards From | Added | Note`), so the mapping exists and is
maintained by the thing that creates the forward.

That is a far better signal than the candidate's name, which two offices can
share. Gmail stamps a forward with the mailbox it came through, so the result
says whose it is.

Where the address is missing or unknown, the BOARD decides as a fallback: a
person is on exactly one office's week. Somebody on two boards is REPORTED and
ticked on neither — the OwnerVille sweep's rule — because a background check
recorded against the wrong person at the wrong office is worse than one that
needs a human to place.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from automations.icd_onboarding import board as B

# The inbox the ICDs forward to. Theirs alone — see the note above.
INBOX = os.environ.get("ICD_STERLING_INBOX", "lucysterlingreports@gmail.com")

# EVERY status goes on the board, not only the finished ones. Megan,
# 2026-11-09: "a status could also be Sent but not taken", "or not sent". The
# cell says where the check has got to, so somebody chasing can tell the
# difference between "nobody sent it" and "it is out and we are waiting" --
# which are different jobs for different people.
#
# Blank means NOT SENT. It is left blank rather than written, so the printed
# sheet still counts it as outstanding and the chase list is right.
DONE_STATUSES = ("Passed", "Failed", "Unperformable", "Complete")


# The app password for that inbox, already installed and named by the Sterling
# install (`set_lucysterling_app_password`). ITS OWN FILE, not raffi127's: the
# reader defaults to the main reporting account, so pointing only the ADDRESS
# at this inbox authenticates the wrong mailbox's password against it and
# Gmail answers "Invalid credentials" — which reads like a dead inbox rather
# than the wiring mistake it is.
APP_PW_PATH = os.environ.get("ICD_STERLING_APPPW_PATH", "")


def _creds() -> Dict[str, str]:
    from automations.icd_alerts import code_answer as CA
    return {"BGSYNC_IMAP_ACCOUNT": INBOX,
            "BGSYNC_IMAP_APPPW_PATH": APP_PW_PATH or str(CA.RESULTS_APP_PW)}


def events(since_days: int = 30, verbose: bool = True) -> List:
    """Parsed Sterling events from the ICDs' inbox.

    Reuses bg_check_sync's reader wholesale — the parsing, the compliance rule
    about never inferring a pass, and the de-duplication are all its.
    """
    from automations.bg_check_sync import email_source

    before = {k: os.environ.get(k) for k in _creds()}
    os.environ.update(_creds())
    try:
        import importlib
        importlib.reload(email_source)
        return email_source.fetch_events(since_days=since_days, verbose=verbose)
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _name_of(ev) -> str:
    return ("%s %s" % (getattr(ev, "first", ""), getattr(ev, "last", ""))).strip()


def office_by_address(book=None) -> Dict[str, str]:
    """{forwarding address: office key}, off the Sterling RESULTS Mail tab.

    Written by the thing that sets an ICD's forward up, so there is no second
    list to keep in step. An address nobody has recorded simply is not here,
    and routing falls back to the board.

    The RESULTS tab, not the codes one: `sterling_forward` runs two separate
    forwards to two separate inboxes — codes to the reporting inbox, results to
    lucysterlingreports@gmail.com — and files them under different services.
    An office can have done one and not the other, so reading the codes tab
    would claim a result forward that does not exist.
    """
    from automations.icd_alerts import code_answer as CA

    out: Dict[str, str] = {}
    try:
        if book is None:
            # The relay workbook, where code_answer files every address an
            # office sends home. Named here the same way code_answer names it.
            from automations.icd_alerts import post as P
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        tab = CA.SERVICES[CA.STERLING_RESULTS]["tab"]
        ws = book.worksheet(tab)
        grid = ws.get_all_values()
    except Exception:          # noqa: BLE001 — no tab yet is not an error
        return out
    if not grid:
        return out
    head = [str(h).strip().lower() for h in grid[0]]
    try:
        oi, ai = head.index("office"), head.index("forwards from")
    except ValueError:
        return out
    for row in grid[1:]:
        if len(row) <= max(oi, ai):
            continue
        office = str(row[oi]).strip().lower()
        addr = str(row[ai]).strip().lower()
        if office and addr:
            out[addr] = office
    return out


def route(events_in: Iterable, boards: Dict[str, List[Dict]],
          by_address: Optional[Dict[str, str]] = None) -> Tuple[Dict, List]:
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
    best: Dict[str, int] = {}
    for ev in events_in or ():
        status = str(getattr(ev, "status", "") or "").strip()
        if not status:
            continue
        name = _name_of(ev)
        # The address that forwarded it, first — it SAYS whose this is.
        sender_office = (by_address or {}).get(
            str(getattr(ev, "forwarded_to", "") or "").strip().lower())
        if sender_office:
            offices = [sender_office]
        else:
            offices = where.get(B._fold(name.replace(" ", "")), [])
        if len(offices) == 1:
            # The inbox carries every mail in the window, so somebody has a
            # Sent AND a Passed. The furthest-along one is the status.
            rank = B.status_rank(status)
            if rank >= best.get(name, -1):
                best[name] = rank
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

    routed, ambiguous = route(got, boards, office_by_address())
    for a in ambiguous:
        log("  ⚠️  %s is on %d boards (%s) — not ticked anywhere"
            % (a["name"], len(a["offices"]), ", ".join(a["offices"])))

    total = 0
    for office, people in routed.items():
        log("  %s: %d check(s) with a status" % (office, len(people)))
        if office not in books:
            # The address says whose it is, but that office has no board for
            # this week. Said out loud rather than dropped: a result nobody
            # can file is exactly the thing this report exists to surface.
            log("    held — %s has no board for this week (%s)"
                % (office, ", ".join(sorted(people))))
            continue
        total += F.apply(books[office], week, "sterling",
                         {n: {"BG Status": s} for n, s in people.items()},
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
