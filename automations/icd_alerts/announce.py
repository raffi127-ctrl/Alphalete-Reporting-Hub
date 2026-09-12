"""Tell an office's channel that Lucy is now watching it. Once, on the day.

  python -m automations.icd_alerts.announce                 # preview all
  python -m automations.icd_alerts.announce --office kash
  python -m automations.icd_alerts.announce --send

WHY A SEPARATE COMMAND and not a line in the poster: this is a one-off that a
person decides to send, to a room of twenty or a hundred people, and it should
never be something a scheduled job can decide to repeat. It posts only to
channels a human has already APPROVED, so it cannot introduce a room that the
alerts themselves would not reach.

DRY RUN IS THE DEFAULT, and --send refuses to run anywhere that does not post
as Lucy Reporting. From Megan's laptop the same command would announce Lucy in
an ICD's channel under Megan's own name.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

from automations.icd_alerts import offices as O, post as P

# Deliberately short (Megan 2026-09-12). It lands in a room of reps who did not
# ask for it, so it earns its place by saying what will now appear and nothing
# else.
HEAD = ":wave: *Lucy is now watching this office's numbers.*"
INTRO_TWO = "From today you'll see two things in here automatically:"
INTRO_ONE = "From today you'll see this in here automatically:"
LINE_ALERTS = "• :mag: a heads-up the moment a rep runs a credit check"
LINE_KNOCKS = "• :door: your knocks & dispositions board, {cadence}"


def _cadence_phrase(dests: List[Dict]) -> str:
    if not dests:
        return ""
    labels = {int(d.get("cadence_min") or 0) for d in dests}
    if labels == {0}:
        return "at first knocks, money lap and end of day"
    m = min(x for x in labels if x) if any(labels) else 0
    if m == 60:
        return "once an hour"
    return "every %d minutes" % m if m else "on a set schedule"


def knocks_is_real(office_key: str, book=None) -> bool:
    """Has this office's laptop ACTUALLY handed over a knocks read?

    APPROVAL IS NOT EVIDENCE. A knocks destination can be signed off while the
    office's OwnerVille login does not work -- which is exactly where Kash was
    an hour before this was written: approved, and failing with "signed in but
    it did not open a working session". Announcing a board to a hundred people
    on the strength of an approval would have been a promise the machine could
    not keep.
    
    A row on 'ICD Knocks' is the proof, because only a successful sign-in and
    grid read can put one there. An EMPTY grid still counts: Cyrus's read at
    10:20am returned no reps because his office starts at 1:30pm, and that is
    a working login reporting a quiet morning.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet("ICD Knocks").get_all_values()
    except Exception:  # noqa: BLE001
        return False
    return any((r[0] or "").strip().lower() == office_key.strip().lower()
               for r in rows[1:] if r)


def message_for(office, knocks: List[Dict], board_works: bool) -> str:
    lines = [HEAD, ""]
    if knocks and board_works:
        lines += [INTRO_TWO, LINE_ALERTS,
                  LINE_KNOCKS.format(cadence=_cadence_phrase(knocks))]
    else:
        lines += [INTRO_ONE, LINE_ALERTS]
    return "\n".join(lines)


def run(*, send: bool = False, only: Optional[str] = None, log=print) -> int:
    approved = P.approved_channels()
    knocks = P.approved_knocks()
    posted = 0

    for office in O.active():
        if only and office.key != only.strip().lower():
            continue
        rooms = approved.get(office.key) or []
        if not rooms:
            log("%-10s no approved channel — nothing to announce in" % office.key)
            continue
        office_knocks = knocks.get(office.key) or []
        board_works = bool(office_knocks) and knocks_is_real(office.key)
        if office_knocks and not board_works:
            log("%-10s knocks approved but its laptop has never handed one "
                "over — the board line is LEFT OUT rather than promised"
                % office.key)
        text = message_for(office, office_knocks, board_works)
        log("\n%-10s -> %s" % (office.key,
                               ", ".join(c.name for c in rooms)))
        for line in text.splitlines():
            log("    %s" % line)
        if not send:
            continue
        for room in rooms:
            try:
                P._slack(room.id, text)
                posted += 1
                log("    posted to %s" % room.name)
            except Exception as e:  # noqa: BLE001 — one room must not cost the rest
                log("    FAILED %s: %s: %s" % (room.name, type(e).__name__,
                                               str(e)[:120]))
    if not send:
        log("\nDRY RUN — nothing posted. Add --send to post for real.")
    return posted


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Announce Lucy in an office's channel")
    ap.add_argument("--send", action="store_true", help="actually post")
    ap.add_argument("--office", help="limit to one office key")
    args = ap.parse_args(argv)
    if args.send:
        P.assert_posting_as_lucy()
    run(send=args.send, only=args.office)
    return 0


if __name__ == "__main__":
    sys.exit(main())
