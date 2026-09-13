"""Fill 'DOB LUCY' from the paperwork we already hold. Read-only upstream.

Megan's point when Raf offered to add birthdates to the sales board (2026-09-13):
*"I already pull DOB off of Blueink."* True -- `apex_new_starts/blueink_data.py`
reads `dob` off each new start's signed I-9 (the I-9 is first in DOC_PREFERENCE,
and SHAPE['dob'] shape-checks it, so a shifted field_map key REFUSES rather than
passing a wrong date through). What was missing is that nothing KEPT it: the
value went straight into Apex and was never written anywhere durable.

This closes that gap without asking anyone to hand-maintain a column. Two ways
in, and both are append-only -- a name already on the tab is never overwritten.

  python -m automations.birthday_reminders.backfill --names "Ann Lee,Bob Cruz"
  python -m automations.birthday_reminders.backfill --board      # this week's roster
  python -m automations.birthday_reminders.backfill --board --send

DRY RUN BY DEFAULT. With no --send it prints exactly what it would add.

THE YEAR NEVER LANDS IN THE SHEET. `store.mmdd()` throws it away on the way in:
a full date of birth is PII with no purpose here, and MM/DD is all a "whose
birthday is tomorrow" check ever asks.

WHO IT DOES NOT COVER: people hired before this ran who are not on the current
board. Their DOB is on their Apex profile (`apex.py` maps 'dob' ->
'date of birth'), which is a browser scrape, not an API read -- so that pass is
deliberately NOT automated here. Raf's office is small enough that the board
sweep plus new hires arriving through apex_new_starts closes the gap within a
few weeks on its own.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.birthday_reminders import config as C
from automations.birthday_reminders import store as S

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# Rows on the board that are not people. `board._unmarked_names` returns every
# unmarked NAME CELL, which is right for the question it was built for ("is this
# person gone?") but not for this one: read live on WE 9.13 its 169 rows include
# 'TOTALS', 'Goal', 'Teams', three copies of '% of Reps on the Board', and the
# team names themselves ('Ceaseless', 'Alphaletes', 'Hashiras', "Zach's").
# Looking those up in Blue Ink would be ~10 wasted API calls and a confusing
# run. Filtered HERE rather than in liveness.py, whose job is to answer about a
# name somebody asked about -- a label will never be in the birthday store.
_NOT_A_PERSON = ("total", "goal", "team", "average", "board", "week", "count")


def is_person(name: str) -> bool:
    """A board row that looks like somebody's name rather than a section label.

    Two tokens minimum ('Ceaseless', "Zach's" are teams), no '%' ('% of Reps on
    the Board'), and no summary word ('Alphaletes Totals' passes the token test
    and is still not a person).
    """
    s = " ".join(str(name or "").split())
    if not s or "%" in s or len(s.split()) < 2:
        return False
    low = s.lower()
    return not any(w in low for w in _NOT_A_PERSON)


def board_names(today: dt.date, *, logfn=print) -> list:
    """Who to look up: the site roster if it has this office, else the board.

    NOTE THE DIFFERENT BAR TO liveness.read(). That one refuses to TRUST the
    site roster until it has recorded a termination, because a roster where
    everyone reads 'Active' cannot suppress anybody. Here we only want a list of
    names to look birthdays up for -- a stale name costs one wasted Blue Ink
    lookup, not a text to somebody we fired -- so the seeded roster is good
    enough, and its names are cleaner than the board's (no section labels, no
    '(Wk 3)' suffixes).
    """
    from automations.birthday_reminders import liveness as L
    reps = L.site_roster()
    if reps:
        logfn("  %d name(s) from the site roster" % len(reps))
        return [r.name for r in reps if is_person(r.name)]

    from automations.terminated_reps import board as B
    marked = B.marked_names(today, logfn=logfn)
    people = [n for n in marked.active if is_person(n)]
    dropped = len(marked.active) - len(people)
    if dropped:
        logfn("  (ignored %d non-person row(s) -- totals, goals, team names)"
              % dropped)
    return people


def _mapped_dob(bundle_id: str, mapping) -> str:
    """The 'dob' value in one bundle, straight off its field rows. '' if absent."""
    from automations.apex_new_starts import blueink_data as BD
    want = {k for d in mapping.values() if isinstance(d, dict)
            for k, v in d.items() if v == "dob"}
    if not want:
        return ""
    for row in BD.bundle_data(bundle_id) or []:
        if isinstance(row, dict) and row.get("field_key") in want:
            got = S.mmdd(row.get("value") or "")
            if got:
                return got
    return ""


def _second_look(name: str, mapping, *, logfn=print) -> str:
    """When the main path finds no DOB, check the person's OTHER bundles.

    THE CASE THIS EXISTS FOR (Deavion Allen, 2026-09-13). He has TWO complete
    bundles: a 1-document one carrying only the W-4, and a 3-document one with
    the I-9. `blueink_data.index_by_person` keys by person and keeps ONE bundle
    per name, so it handed back the W-4-only one -- which maps to zero fields --
    and he was reported as having no usable date of birth. His I-9 has it:
    1999-05-22.

    Fixed HERE rather than in `blueink_data.for_people` on purpose. That module
    is the shared path `apex_new_starts` types Socials and payroll details
    through; changing which bundle it picks is a real change to a live report
    and is Megan's call, not a side effect of a birthday feature. What this does
    is read-only and scoped to this one report. THE UNDERLYING PICK IS STILL
    WRONG FOR apex_new_starts -- anyone with two bundles fills from the thinner
    one -- and that is worth raising separately.
    """
    from automations.apex_new_starts import blueink_data as BD
    surname = str(name or "").split()[-1] if name else ""
    if not surname:
        return ""
    try:
        hits = BD.search_bundles(surname, limit=10)
    except Exception as e:  # noqa: BLE001
        logfn("        (second look failed for %s: %s)" % (name, str(e)[:60]))
        return ""
    key = BD._key(name)
    for b in hits:
        signers = [s.get("name") or "" for s in (b.get("packets") or [])]
        if not any(BD._key(s) == key for s in signers):
            continue
        got = _mapped_dob(b.get("id") or "", mapping)
        if got:
            return got
    return ""


def gather(names: list, *, logfn=print) -> list:
    """Look each name up in Blue Ink -> [store.Entry] for the ones with a DOB.

    One sweep of the bundle list for the whole cohort (`for_people` does this
    deliberately -- a per-person search would rate-limit the account).
    """
    from automations.apex_new_starts import blueink_data as BD
    from automations.apex_new_starts import fieldmap as FM
    today = dt.date.today().isoformat()
    mapping = FM.load()
    hires = BD.for_people(names, mapping)

    out, gaps = [], []
    for name, hire in hires.items():
        if hire.missing_packet:
            gaps.append((name, "no signed packet found"))
            continue
        got = S.mmdd((hire.values or {}).get("dob", ""))
        source = "blueink"
        if not got:
            got = _second_look(name, mapping, logfn=logfn)
            if got:
                source = "blueink (2nd bundle)"
        if not got:
            gaps.append((name, "packet has no date of birth filled in"))
            continue
        out.append(S.Entry(name=name, mmdd=got, source=source, added=today))
    for name, why in gaps:
        logfn("  --    %s -- %s" % (name, why))
    return out


def run(names: list, *, dry_run: bool = True, logfn=print) -> int:
    if not names:
        logfn("no names to look up.")
        return 0
    logfn("looking up %d name(s) in Blue Ink..." % len(names))
    found = gather(names, logfn=logfn)
    res = S.append(found, dry_run=dry_run)

    for name in res["added"]:
        got = next((e.mmdd for e in found if e.name == name), "")
        logfn("  %s %s -- %s" % ("ADD " if not dry_run else "would add", name, got))
    for name, why in res["skipped"]:
        logfn("  --    %s -- %s" % (name, why))
    for name, have, fresh in res["conflicts"]:
        # Never resolved silently: two different birthdays for one person is a
        # question for a human, and the stored one is left exactly as it was.
        logfn("  ⚠ %s -- tab says %s, Blue Ink says %s. LEFT ALONE; check by hand."
              % (name, have, fresh))
    logfn("%s %d row(s)%s"
          % ("wrote" if not dry_run else "(dry run) would write",
             len(res["added"]), "" if not dry_run else " -- re-run with --send"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fill the 'DOB LUCY' tab from signed Blue Ink packets.")
    ap.add_argument("--names", help="Comma-separated names to look up.")
    ap.add_argument("--board", action="store_true",
                    help="Look up everyone working on this week's sales board.")
    ap.add_argument("--date", help="Pretend today is this YYYY-MM-DD (testing).")
    ap.add_argument("--send", action="store_true",
                    help="Actually write to the tab (default is a dry run).")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    names = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    if args.board:
        names += board_names(today)
    if not names:
        ap.error("give it --names, or --board to sweep this week's roster.")
    return run(names, dry_run=not args.send)


if __name__ == "__main__":
    # Non-technical people run these from the Hub. A traceback is not an error
    # message -- print the sentence and nothing else. [[7-year-old-simple]]
    try:
        sys.exit(main())
    except S.StoreError as e:
        print("\u26a0 %s" % e)
        sys.exit(1)
