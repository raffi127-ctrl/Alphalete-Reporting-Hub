"""The three columns only a person fills: Classroom, Gender, Location.

The panel writes these through the Apps Script relay. This is the same write
from a command line, for when somebody is doing a whole week at once rather
than clicking twenty-two pick lists -- and for an office whose panel is not
set up yet.

IT NEVER GUESSES. A name is not evidence of a gender, and the value lands on
a payroll record. Only names it was given are written, only on the week it
was given, and only when the value actually differs.

    PYTHONPATH=. .venv/bin/python -m automations.icd_onboarding.by_hand \
        --office raf --column Gender --set "Stacy Alberty=Female" --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F
from automations.icd_onboarding import sheet as S

# Exactly how Apex's own dropdown spells them, so what is written here is what
# gets typed into Apex. Kept in step with the panel's own list.
GENDERS = ("Female", "Male")


def _key(name: str) -> str:
    return "".join(c for c in str(name or "").lower() if c.isalnum())


def plan(rows: List[Dict], column: str, want: Dict[str, str]) -> List[Dict]:
    """[{row, name, from, to}] -- only what actually changes.

    A name nobody on the board answers to is NOT written anywhere: it is
    reported, because the likeliest reason is a spelling that differs from
    the board's and the second likeliest is the wrong week.
    """
    byk = {_key(k): str(v or "").strip() for k, v in (want or {}).items()}
    out, seen = [], set()
    for r in rows:
        full = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        k = _key(full)
        if k not in byk:
            continue
        seen.add(k)
        now = str(r.get(column) or "").strip()
        if now == byk[k]:
            continue
        out.append({"row": r, "name": full, "from": now, "to": byk[k]})
    for k, v in byk.items():
        if k not in seen:
            out.append({"row": None, "name": k, "from": "", "to": v})
    return out


def write(office_key: str, column: str, want: Dict[str, str],
          week_start: Optional[dt.date] = None, *, dry_run: bool = False,
          log=print) -> int:
    if column not in B.BY_HAND:
        raise RuntimeError(
            "%r is not one of the by-hand columns (%s). Everything else is "
            "filled from its own source and must not be typed over."
            % (column, ", ".join(B.BY_HAND)))
    if column == B.GENDER:
        odd = sorted({v for v in want.values() if v and v not in GENDERS})
        if odd:
            raise RuntimeError(
                "Apex spells these %s, so %s would never match its dropdown."
                % (" / ".join(GENDERS), ", ".join(repr(o) for o in odd)))

    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        log("  no onboarding board for %s yet." % office_key)
        return 0
    grid = ws.get_all_values()
    cols = S.layout(grid)
    if column not in cols:
        raise RuntimeError(
            "the board has no %r column. If it was renamed, rename it here "
            "too -- this never guesses at a position." % column)
    all_rows = S.rows_of(grid)
    week = week_start or B.week_start_of(dt.date.today())
    mine = B.for_week(all_rows, week)
    todo = plan(mine, column, want)

    missing = [t for t in todo if t["row"] is None]
    for t in missing:
        log("  NOT ON THE WEEK OF %s: %r -- check the spelling, or the week."
            % (B.week_label(week), t["name"]))
    todo = [t for t in todo if t["row"] is not None]
    for t in todo:
        log("  %-28s %r -> %r" % (t["name"], t["from"], t["to"]))
    if not todo:
        log("  nothing to change.")
        return 0
    if dry_run:
        log("  --dry-run: nothing written.")
        return 0

    a1 = S._a1(cols[column] + 1)
    ws.batch_update([
        {"range": "%s%d" % (a1, S.FIRST_DATA_ROW + all_rows.index(t["row"])),
         "values": [[t["to"]]]} for t in todo])
    log("  wrote %d." % len(todo))
    return len(todo)


def _pairs(args: Sequence[str]) -> Dict[str, str]:
    out = {}
    for a in args or ():
        if "=" not in a:
            raise SystemExit("--set wants Name=Value, got %r" % a)
        name, _, val = a.partition("=")
        out[name.strip()] = val.strip()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="raf")
    ap.add_argument("--column", default=B.GENDER,
                    help="Classroom, Gender or Location")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help='e.g. --set "Stacy Alberty=Female"')
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.set:
        ap.error("--set is required")
    week = B.week_start_of(dt.date.fromisoformat(a.week)) if a.week else None
    write(a.office, a.column, _pairs(a.set), week,
          dry_run=a.dry_run, log=print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
