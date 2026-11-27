"""Card step 2.6: do AppStream's numbers match what the interviewers typed?

Builds every box twice for the same weeks -- once from AppStream (read.py's
cached Calendar days), once from the ARS tab's typed rows -- and compares them.
Prints, per week, each block's totals side by side, then the share of
interviewer cells that agree. Nothing is written anywhere.

    python -m automations.interviewer_retention.compare --office 11280 --tab "Rafael Hidalgo" --weeks 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import check as ck
from automations.interviewer_retention import from_calendar as fc
from automations.interviewer_retention import read as rd

SUMS = {"qualified": ("Q", "Di", "De"), "answered": ("Q", "A", "B"),
        "second": ("B", "S", "NS", "RR", "C")}


def _tot(box: List[Dict], block: str) -> Dict[str, int]:
    out = {k: 0 for k in SUMS[block]}
    for r in box:
        for d in r["days"]:
            for k in out:
                out[k] += int(d.get(k, 0))
    return out


def _cells(box: List[Dict]) -> Dict[tuple, float]:
    out = {}
    for r in box:
        for i, d in enumerate(r["days"]):
            for k, v in d.items():
                if not k.endswith("R"):                # counts only, not percents
                    out[(r["interviewer"], i, k)] = v
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.compare")
    ap.add_argument("--office", default="11280")
    ap.add_argument("--sheet", default=ck.ARS_R_TO_Z)
    ap.add_argument("--tab", default="Rafael Hidalgo")
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--last-sunday", default="", help="YYYY-MM-DD (default: last Sunday)")
    a = ap.parse_args(argv)
    from automations.recruiting_report.fill import open_by_key
    grid = open_by_key(a.sheet).worksheet(a.tab).get_all_values(value_render_option="UNFORMATTED_VALUE")
    typed = ck.interviews(grid)
    days = rd.load_cache(a.office)
    as_rows, unknown, orphans = rd.build(days, fc.load_names(a.office))
    today = dt.date.today()
    end = (dt.date.fromisoformat(a.last_sunday) if a.last_sunday
           else today - dt.timedelta(days=(today.weekday() + 1) % 7))
    anchors = [end - dt.timedelta(weeks=i) for i in range(a.weeks)][::-1]
    agree = total = 0
    print(f"{a.tab} ({a.office}): AppStream vs typed, {len(anchors)} weeks")
    print(f"  unknown Done By names: {dict(unknown) or 'none'} | 2nd rounds with no 1st round found: {len(orphans)}")
    for anchor in anchors:
        mine, theirs = bx.week(as_rows, anchor), bx.week(typed, anchor)
        parts = []
        for block in ck.BLOCKS:
            t1, t2 = _tot(mine[block], block), _tot(theirs[block], block)
            parts.append(f"{block[:4]} " + " ".join(f"{k} {t1[k]}/{t2[k]}" for k in SUMS[block]))
            c1, c2 = _cells(mine[block]), _cells(theirs[block])
            for key in set(c1) | set(c2):
                total += 1
                agree += int(c1.get(key, 0) == c2.get(key, 0))
        print(f"  week {anchor:%m/%d} (AppStream/typed): " + " | ".join(parts))
    print(f"  interviewer-by-day cells that agree: {agree} of {total} ({100 * agree / max(total, 1):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
