"""Drop the stale '(Wk 2)' / '(Wk 3)' suffix from rep tab names.

A rep's tab in 'Local Office Reps - Focus Reports - raf' is born with whatever
the sales board called them that week, suffix and all — and then it FREEZES,
while the board's own suffix keeps moving ('(Wk 2)' -> '(Wk 3)' -> dropped).
Six months later the workbook still has a 'Zoria Johnson (Wk 2)' tab for
someone in their fifth month. This renames those back to just the name.

STALE IS CHECKED, NOT ASSUMED. Eve's rule is "si ya no son week 2" — so each
suffix is compared against that rep's 'Field Status' on the NEWEST sales board
(the column the report already treats as the reliable one; the suffix is only
its fallback). '(Wk 2)' + '2nd Wk' still agree, so that tab is left alone.
'(Wk 2)' + '5th wk+', or a rep no longer on the board at all, is stale and gets
renamed.

ONLY THE WEEK SUFFIX IS TOUCHED. 'Keitydrick Branch (KB) (Wk 2)' becomes
'Keitydrick Branch (KB)' — (KB) is his nickname, and (NC), (GiGi), (Ivette),
(Samajai), (Bella) are all names people go by. Stripping those would rename a
person out of recognition.

RENAMING IS SAFE FOR THE REPORT. Every join in reps_gross_paycheck goes through
names.key(), which drops parentheticals before matching, so the tab still binds
to the same person on the sales board and in the PNL afterwards — and so does
aliases.json, whose keys normalize the same way. Google rewrites same-workbook
formula references on a rename by itself. Nothing outside this module addresses
these tabs by title (checked 2026-08-07).

  python -m automations.reps_gross_paycheck.clean_tab_names           # preview
  python -m automations.reps_gross_paycheck.clean_tab_names --apply   # rename
"""
from __future__ import annotations

import argparse
import re
import sys

from automations.recruiting_report.fill import open_by_key
from automations.reps_gross_paycheck import names, records, sales_board

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ' (Wk 2)' anywhere in the title, with the space in front so the rename leaves
# no double space behind.
WK_SUFFIX = re.compile(r"\s*\(\s*wk\s*(\d+)\s*\)", re.I)

# 'Field Status' vocabulary -> the week number it means. '5th wk+', 'RT' and
# 'Extra' deliberately map to nothing: none of them is "still week N".
STATUS_WEEK = re.compile(r"^\s*(\d+)(?:st|nd|rd|th)\s*wk\s*$", re.I)


def clean(title: str) -> str:
    """'Jose Calixto (Wk 2)' -> 'Jose Calixto'. Other parentheticals stay."""
    return " ".join(WK_SUFFIX.sub("", title).split())


def status_week(status: str) -> int | None:
    """'2nd Wk' -> 2. '5th wk+' / 'RT' / 'Extra' / '' -> None."""
    m = STATUS_WEEK.match(str(status or ""))
    return int(m.group(1)) if m else None


def plan(logfn=print) -> list[tuple]:
    """[(worksheet, old, new, why)] for the tabs whose suffix has gone stale."""
    board_sh = open_by_key(sales_board.SHEET_ID)
    weeks = sales_board.week_tabs(board_sh)
    if not weeks:
        raise RuntimeError("no 'Sales Board WE m.d' tabs on the sales board.")
    newest = weeks[-1][0]
    reps = sales_board.load(board_sh, sundays=[newest])
    logfn(f"  newest board: week ending {newest.isoformat()} "
          f"({len(reps)} reps)")

    sh = open_by_key(records.SHEET_ID)
    out = []
    for ws in sh.worksheets():
        m = WK_SUFFIX.search(ws.title)
        if not m:
            continue
        tab_week = int(m.group(1))
        rep = reps.get(names.key(ws.title))
        status = rep.status_by_week.get(newest, "") if rep else ""
        now = status_week(status)
        if now == tab_week:
            logfn(f"  keep   {ws.title!r} — the board still says "
                  f"{status!r}")
            continue
        why = (f"board says {status!r}" if rep
               else "not on the newest board")
        out.append((ws, ws.title, clean(ws.title), why))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually rename (default: preview only)")
    args = ap.parse_args(argv)

    rows = plan()
    if not rows:
        print("Nothing to rename — every '(Wk N)' tab still matches the board.")
        return 0

    print(f"\n{len(rows)} tab(s) to rename:")
    for _ws, old, new, why in rows:
        print(f"  {old!r}\n     -> {new!r}   ({why})")

    # A rename that collides with an existing tab would fail mid-loop and leave
    # the workbook half-renamed, so catch it before touching anything.
    existing = {w.title for w in open_by_key(records.SHEET_ID).worksheets()}
    clashes = [new for _w, old, new, _y in rows
               if new in existing and new != old]
    if clashes:
        print(f"\n❌ these names are already taken by another tab: {clashes}. "
              f"Two tabs for one rep is a real problem — merge them by hand "
              f"first. Nothing renamed.")
        return 1

    if not args.apply:
        print("\n(preview — nothing renamed. Re-run with --apply.)")
        return 0

    for ws, old, new, _why in rows:
        ws.update_title(new)
        print(f"  ✓ {old!r} -> {new!r}")
    print(f"\nRenamed {len(rows)} tab(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
