"""Does boxes.py reproduce the ARS tab? (card step 2.4: "just make sure we match it")

Reads one owner's ARS tab, rebuilds every week box from the tab's own typed
rows with boxes.py, and compares each number with what the tab's formulas show.
Nothing is written anywhere.

Boxes are found by their labels, never by fixed cells: the three blocks by the
'Interviewer' headers, each week by the date in the first block's label column,
each day group by its day name, each number by its sub-header.

    python -m automations.interviewer_retention.check --weeks 6
    python -m automations.interviewer_retention.check --tab "Rafael Hidalgo" --weeks 6
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

from automations.interviewer_retention import boxes as bx

ARS_R_TO_Z = "16UruNs3bHGJ_pBvmD6T9KEqMAtDNNyuKArA_es6f0LE"
EPOCH = dt.date(1899, 12, 30)

# sub-header text -> boxes.py key, per block
DAY_KEYS = {"qualified": {"Q": "Q", "Di": "Di", "De": "De", "QR": "QR", "DiR": "DiR", "DR": "DR"},
            "answered": {"Q": "Q", "A": "A", "B": "B", "NC": "NC", "AR": "AR", "BR": "BR", "NCR": "NCR"},
            "second": {"B": "B", "S": "S", "NS": "NS", "RR": "RR", "C": "C", "R": "R"}}
TOTAL_KEYS = {"qualified": {"qualified": "Q", "disqualified": "Di", "declined": "De",
                            "qualified retention": "QR", "disqualified retention": "DiR",
                            "declined retention": "DR"},
              "answered": {"qualified": "Q", "answered": "A", "booked": "B", "not contacted": "NC",
                           "answered retention": "AR", "booked retention": "BR",
                           "not contacted retention": "NCR"},
              "second": {"2nd rd booked": "Booked", "2nd rd showed": "Showed",
                         "2nd showed retention": "R"}}
BLOCKS = ("qualified", "answered", "second")
CANON = {v.lower(): v for v in (bx.QUALIFY, bx.DISQUALIFY, bx.DECLINED, bx.ANSWERED, bx.NO_ANSWER,
                                 bx.NOT_CONTACTED, bx.BOOKED, "Not Booked", bx.SHOWED, bx.NO_SHOW,
                                 bx.RESCHEDULE, bx.CANCELLED)}


def _date(v) -> Optional[dt.date]:
    return EPOCH + dt.timedelta(days=int(v)) if isinstance(v, (int, float)) and v > 40000 else None


def _txt(v) -> str:
    return "" if v is None else str(v)


def _norm(h) -> str:
    return " ".join(_txt(h).replace("\n", " ").split()).lower()


def interviews(grid: List[List]) -> List[bx.Interview]:
    head = [_norm(h) for h in grid[0]]
    col = {name: head.index(name) for name in ("date 1st rd", "1st round interviewer", "qualify",
                                               "answer call", "booked to 2nd rd", "date 2nd rd",
                                               "showed up to 2nd round")}
    out = []
    for r in grid[1:]:
        g = lambda k: r[col[k]] if col[k] < len(r) else ""          # noqa: E731
        d1 = _date(g("date 1st rd"))
        if not d1 and not _date(g("date 2nd rd")):
            continue
        v = lambda k: CANON.get(_txt(g(k)).strip().lower(), _txt(g(k)).strip())  # noqa: E731
        out.append(bx.Interview(interviewer=_txt(g("1st round interviewer")), date1=d1,
                                qualify=v("qualify"), answer=v("answer call"),
                                booked=v("booked to 2nd rd"), date2=_date(g("date 2nd rd")),
                                show2=v("showed up to 2nd round")))
    return out


BANNERS = {"qualified": "qualified retention", "answered": "answered / booked retention",
           "second": "2nd rd showed retention"}


def layout(grid: List[List]) -> Tuple[List[int], List[int], Dict[int, Optional[int]]]:
    """([interviewer column of each of our 3 blocks], [row of every week label],
    {block column: the next block's column, where its numbers stop}).
    A block is its row-1 banner over an 'Interviewer' header (the tab has more
    blocks to the right -- Offered / BOB etc. -- which we leave alone)."""
    for r in grid[:40]:
        heads = [j for j, c in enumerate(r) if _norm(c) == "interviewer"]
        if len(heads) >= 3:
            top = grid[0]
            cols = []
            for block in BLOCKS:
                hit = [j for j in heads if j < len(top) and _norm(top[j]) == BANNERS[block]]
                if not hit:
                    raise RuntimeError(f"no '{BANNERS[block]}' banner over an Interviewer header")
                cols.append(hit[0])
            nxt = {c: next((h for h in heads if h > c), None) for c in cols}
            first = cols[0]
            labels = [k for k, row in enumerate(grid)
                      if first < len(row) and _date(row[first])
                      and k + 1 < len(grid) and first < len(grid[k + 1])
                      and _norm(grid[k + 1][first]) == "interviewer"]
            return cols, labels, nxt
    raise RuntimeError("no row with the 'Interviewer' headers: not an ARS tab?")


def read_box(grid, label_row: int, c0: int, c_next: Optional[int], block: str) -> Dict[str, Dict]:
    """{interviewer: {'days': [{key: val}], 'total': {key: val}}} as the tab shows it."""
    days_row, sub_row = grid[label_row], grid[label_row + 1]
    end = c_next if c_next else len(sub_row)
    groups, cur = [], None
    for j in range(c0 + 1, end):
        day = _norm(days_row[j]) if j < len(days_row) else ""
        if day:
            cur = {"name": day, "cols": []}
            groups.append(cur)
        if cur is not None and j < len(sub_row) and _txt(sub_row[j]).strip():
            cur["cols"].append((j, _txt(sub_row[j]).strip()))
    out = {}
    for row in grid[label_row + 2:]:
        name = _txt(row[c0]) if c0 < len(row) else ""
        if not name.strip() or _date(name):
            break
        rec = {"days": [], "total": {}}
        for g in groups:
            keys = TOTAL_KEYS[block] if g["name"].startswith("total") else DAY_KEYS[block]
            vals = {keys[_norm(h) if g["name"].startswith("total") else h]: (row[j] if j < len(row) else "")
                    for j, h in g["cols"]
                    if (_norm(h) if g["name"].startswith("total") else h) in keys}
            (rec.__setitem__("total", vals) if g["name"].startswith("total") else rec["days"].append(vals))
        out[name] = rec
    return out


def _same(a, b) -> bool:
    try:
        return abs(float(a or 0) - float(b or 0)) < 1e-6
    except (TypeError, ValueError):
        return _txt(a) == _txt(b)


def compare(grid, weeks: int, today: dt.date) -> Tuple[int, List[str]]:
    rows = interviews(grid)
    cols, labels, nxt = layout(grid)
    last_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    picks = [k for k in labels if _date(grid[k][cols[0]]) <= last_sunday][-weeks:]
    checked, diffs = 0, []
    for k in picks:
        anchor = _date(grid[k][cols[0]])
        mine = bx.week(rows, anchor)
        for b, block in enumerate(BLOCKS):
            # every block carries its own week label; the 2nd-round box may sit on another row
            row_k = k
            if b and not _date(grid[k][cols[b]] if cols[b] < len(grid[k]) else None):
                continue
            sheet = read_box(grid, row_k, cols[b], nxt[cols[b]], block)
            calc = {r["interviewer"]: r for r in mine[block]}
            for name, got in sheet.items():
                want = calc.get(name)
                if not want:
                    if any(not _same(v, 0) for d in got["days"] for v in d.values()):
                        diffs.append(f"{anchor:%m/%d} {block}: {name!r} on the tab, not computed")
                    continue
                for i, d in enumerate(got["days"]):
                    for key, val in d.items():
                        checked += 1
                        if not _same(val, want["days"][i][key]):
                            diffs.append(f"{anchor:%m/%d} {block} {name} day{i + 1} {key}: "
                                         f"tab {val} vs computed {want['days'][i][key]}")
                for key, val in got["total"].items():
                    checked += 1
                    if not _same(val, want["total"][key]):
                        diffs.append(f"{anchor:%m/%d} {block} {name} TOTAL {key}: "
                                     f"tab {val} vs computed {want['total'][key]}")
            for name in calc:
                if name not in sheet:
                    diffs.append(f"{anchor:%m/%d} {block}: {name!r} computed, not on the tab")
    return checked, diffs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.check")
    ap.add_argument("--sheet", default=ARS_R_TO_Z)
    ap.add_argument("--tab", default="Rafael Hidalgo")
    ap.add_argument("--weeks", type=int, default=6)
    a = ap.parse_args(argv)
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(a.sheet).worksheet(a.tab)
    grid = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    checked, diffs = compare(grid, a.weeks, dt.date.today())
    print(f"{a.tab}: {checked} numbers checked over the last {a.weeks} weeks, {len(diffs)} differ")
    for d in diffs[:60]:
        print("  " + d)
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
