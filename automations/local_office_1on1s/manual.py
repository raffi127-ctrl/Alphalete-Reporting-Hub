"""Carry Raf's hand-typed rows across from the `OLD of ...` tabs.

The five team tabs were rebuilt from the template on 2026-09-28, which means
every NUMBER can be regenerated but nothing Raf TYPED can. Megan, 2026-09-28:
*"Yes, you can pull those from the old sheets."*

WHAT MOVES — only the rows no source can produce:

    What are we going to do better?
    Listening to X book? · Dress Code · Last week Punctuality?
    Atmo Engagement · Slack / Chat Engagement · Networking?
    BreakEven · Money Saved?
    Goal / Focus for the week

`BreakEven` is in that list on purpose: the column exists on every P&L and is
empty for all 446 named reps, so the only BreakEven that has ever existed is
the one Raf typed.

WHAT DOES NOT MOVE: anything with a live source (sales, recruiting, paycheck,
trained/retained). Copying those would freeze a stale hand-entry on top of a
number the fill is about to compute correctly — and the old tabs contain known
bad ones, e.g. Anthony Marchetti's WE 9/13 '2nd Closing %' reading '2'.

MATCHING IS BY PERSON AND BY WEEK, both by label. The old tabs carry the
inconsistent headers this build documented — 'WE 8/02', 'WE  9/4' (a Friday),
'9/13' — so a week that will not resolve to a Sunday is SKIPPED and reported
rather than being written into whatever column sits at that index.

NEVER OVERWRITES. A destination cell that already holds something is left
alone and reported; this only fills blanks. Two tabs were deleted before they
could be backed up (`Alphaletes`, `Mindset Engine`), so for those teams there
is nothing to carry and the run says so instead of silently doing nothing.
"""
from __future__ import annotations

from automations.shared import sheets_retry as RETRY
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import layout as LO, people as PEO, weeks as W

MANUAL_LABELS = [
    "What are we going to do better?",
    "Listening to X book?",
    "Dress Code 1 out of",          # matches both the /3 and /5 spellings
    "Last week Punctuality?",
    "Atmo Engagement 1 out",
    "Slack / Chat Engagement 1 out",
    "Networking?",
    "BreakEven",
    "Money Saved?",
    "Goal / Focus for the week",
]

OLD_PREFIX = "OLD of "


@dataclass
class Move:
    person: str
    label: str
    week: dt.date
    value: str
    dest_row: int
    dest_col: int


@dataclass
class LiftPlan:
    moves: List[Move] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    occupied: List[str] = field(default_factory=list)


def plan(old_grid: List[List[str]], new_grid: List[List[str]],
         *, year: int, team: str) -> LiftPlan:
    out = LiftPlan()
    sections = [s for s in LO.find_sections(new_grid) if s.name.strip()]
    new_secs = {PEO.key(s.name): s for s in sections}
    names = [s.name for s in sections]

    for osec in LO.find_sections(old_grid):
        if not osec.name.strip():
            continue
        # The OLD tabs spell people informally — 'pranish', 'Rhea', 'Andres',
        # 'Willie' — where the rebuilt tabs carry the board's full name. An
        # exact key match found nothing for a whole team (Hashiras: 0 of 5), so
        # resolve through the same matcher the fill uses: it accepts a unique
        # first-name hit and REFUSES an ambiguous one rather than guessing.
        nsec = new_secs.get(PEO.key(osec.name))
        if nsec is None:
            hit, note = PEO.resolve(osec.name, names)
            if hit is not None:
                nsec = new_secs[PEO.key(hit)]
                if note:
                    out.skipped.append(f"{team}: {note} -> {hit}")
        if nsec is None:
            out.skipped.append(f"{team}: {osec.name!r} has no section on the new tab")
            continue

        ohdr = W.read_header(osec.header, year=year)
        nhdr = W.read_header(nsec.header, year=year)
        for bad in [h for h in ohdr if not h.ok]:
            out.skipped.append(f"{team} {osec.name}: old header {bad.raw!r} — {bad.suspect}")

        orows = LO.label_rows(old_grid, osec)
        nrows = LO.label_rows(new_grid, nsec)

        for label in MANUAL_LABELS:
            orow = LO.find_row(orows, label)
            nrow = LO.find_row(nrows, label)
            if orow is None or nrow is None:
                continue
            for ow in [w for w in ohdr if w.ok]:
                nw = W.find(nhdr, ow.sunday)
                if nw is None:
                    continue
                val = LO._cell(old_grid, orow, ow.col).strip()
                if not val or val == "-":
                    continue
                if LO._cell(new_grid, nrow, nw.col).strip():
                    out.occupied.append(
                        f"{team} {osec.name} {label} WE {ow.sunday:%-m/%-d}: "
                        f"destination already filled — left alone")
                    continue
                out.moves.append(Move(osec.name, label, ow.sunday, val, nrow, nw.col))
    return out


def apply(ws, moves: List[Move], *, logfn=print) -> int:
    """Write the planned moves. Blanks only — `plan` already excluded any
    destination that held something."""
    if not moves:
        return 0
    updates = [{"range": f"{_a1(m.dest_col)}{m.dest_row}", "values": [[m.value]]}
               for m in moves]
    for i in range(0, len(updates), 400):
        ws.batch_update(updates[i:i + 400])
    return len(updates)


def _a1(col: int) -> str:
    s = ""
    while col > 0:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def main(argv=None) -> int:
    """python -m automations.local_office_1on1s.manual [--write]"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    from automations.local_office_1on1s.run import BOOK

    book = RETRY.call(open_by_key, BOOK, tries=6)
    titles = [w.title for w in book.worksheets()]
    pairs = [(t, t[len(OLD_PREFIX):]) for t in titles if t.startswith(OLD_PREFIX)]
    pairs = [(o, n) for o, n in pairs if n in titles]
    if not pairs:
        print("no 'OLD of ...' tabs with a matching new tab — nothing to lift")
        return 0

    total = 0
    for old_title, new_title in pairs:
        old_grid = RETRY.call(book.worksheet(old_title).get_all_values, tries=6)
        new_grid = RETRY.call(book.worksheet(new_title).get_all_values, tries=6)
        p = plan(old_grid, new_grid, year=a.year, team=new_title)
        print(f"\n{new_title}  <- {old_title}")
        print(f"  {len(p.moves)} value(s) to carry over")
        by_person = {}
        for m in p.moves:
            by_person.setdefault(m.person, 0)
            by_person[m.person] += 1
        for who, n in sorted(by_person.items()):
            print(f"    {who:<30} {n:>3}")
        for s in dict.fromkeys(p.skipped):
            print(f"    ! {s}")
        for s in list(dict.fromkeys(p.occupied))[:5]:
            print(f"    · {s}")
        if a.write:
            total += apply(book.worksheet(new_title), p.moves)
        else:
            print("  PREVIEW — nothing written")
    print(f"\n{'wrote' if a.write else 'would write'} {total} cell(s)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
