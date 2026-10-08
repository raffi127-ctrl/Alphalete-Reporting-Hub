"""Extend every ICD tab's week columns out to a target Sunday (Eve 2026-10-08:
"todas terminan en 1/3/2027 y ya nos estamos acercando" -> through June 2027).

HOW. The last week column is copied (formulas, formats, conditional-format
coverage, width) into the next N columns, so every per-week formula -- the
retention %s, Badged %, the `=prev+7` header chain -- keeps going on its own.

What does NOT get copied: a typed number in that last column. A future week
should hold formulas only, and a stray hardcoded value there is exactly the
contamination that once rode Template Fiber's AVG row into every new tab
(project_new-tab-copy-carries-foreign-hardcoded-avgs). Typed DATES are the one
literal kept: they are re-written as that column's own week (+7 each).

Refuses a tab, by name, when the columns it would fill aren't empty, or the
workbook would go over Google's 10M-cell cap.

Run:
  python -m automations.recruiting_report.extend_weeks --only "Marcellus Butler" --dry-run
  python -m automations.recruiting_report.extend_weeks --until 2027-06-27
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Optional

from automations.recruiting_report import fill
from automations.recruiting_report.badged import _col_letter, _norm

CELL_CAP = 10_000_000
SKIP_TABS = {"raf hidalgo"}  # master tab: 2-row header, different layout

_EPOCH = dt.date(1899, 12, 30)


def _as_date(v) -> Optional[dt.date]:
    if isinstance(v, (int, float)) and 30000 < v < 60000:
        return _EPOCH + dt.timedelta(days=int(v))
    return None


def plan_tab(sh, ws, until: dt.date, insert: bool = False):
    header = fill._retry(ws.row_values, fill.HEADER_ROW)
    cols = fill.find_sunday_columns([header])
    if len(cols) < 20:
        return None, "not a weekly tab"
    last = max(cols)
    c = cols[last] - 1                   # find_sunday_columns is 1-indexed
    if c != max(cols.values()) - 1 and not insert:  # insert: old columns just shift right
        return None, f"week headers out of order (last date {last} isn't the right-most)"
    n = (until - last).days // 7
    if n <= 0:
        return None, f"already reaches {last}"
    return (last, c, n), ""


def extend_tab(sh, ws, until: dt.date, *, dry_run: bool, budget: List[int],
               insert: bool = False, max_row: Optional[int] = None) -> str:
    """insert=True: open N fresh columns right after the last week instead of
    using the empty ones beyond it -- for a tab where somebody built their own
    block there (Tony Chavez's leads planner). Their block shifts right intact."""
    plan, why = plan_tab(sh, ws, until, insert)
    if not plan:
        return f"skip: {why}"
    last, c, n = plan
    # max_row: only the weekly block is copied; whatever the owner built below
    # it (Tony Chavez's sales planner from row 119) is left exactly where it is.
    rows = min(ws.row_count, max_row) if max_row else ws.row_count
    grow = n if insert else max(0, c + 1 + n - ws.col_count)
    if grow * rows > budget[0]:
        return f"REFUSED: needs {grow * rows} cells, only {budget[0]} left under the 10M cap"

    # target columns must be empty
    if c + 1 < ws.col_count and not insert:
        tgt = fill._retry(ws.get_values,
                          f"{_col_letter(c + 1)}1:{_col_letter(min(c + n, ws.col_count - 1))}{rows}")
        busy = [(i + 1, _col_letter(c + 1 + j)) for i, r in enumerate(tgt)
                for j, v in enumerate(r) if str(v).strip()]
        if busy:
            return f"REFUSED: target columns not empty ({len(busy)} cells, e.g. {busy[:3]})"

    msg = (f"{last} -> {last + dt.timedelta(days=7 * n)} (+{n} weeks"
           f"{f', +{grow} columns' if grow else ''})")
    if dry_run:
        return "would extend " + msg

    sid = ws.id
    src = fill._retry(ws.get_values, f"{_col_letter(c)}1:{_col_letter(c)}{rows}",
                      value_render_option="FORMULA")
    reqs = []
    if insert:
        reqs.append({"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                   "startIndex": c + 1, "endIndex": c + 1 + n},
                                         "inheritFromBefore": True}})
    elif grow:
        reqs.append({"appendDimension": {"sheetId": sid, "dimension": "COLUMNS", "length": grow}})
    meta = fill._retry(sh.fetch_sheet_metadata, {
        "ranges": [f"'{ws.title}'!{_col_letter(c)}1:{_col_letter(c)}1"],
        "fields": "sheets(properties(sheetId),data(columnMetadata(pixelSize)),conditionalFormats,merges)"})
    sm = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == sid)
    # merges come back clipped to `ranges`, so ask for the whole tab's
    whole = fill._retry(sh.fetch_sheet_metadata, {
        "ranges": [f"'{ws.title}'"], "fields": "sheets(properties(sheetId),merges)"})
    sm["merges"] = next(s for s in whole["sheets"]
                        if s["properties"]["sheetId"] == sid).get("merges") or []
    # Somebody's merged box (notes, an image) crossing these columns is theirs:
    # copy around its rows, never through it.
    blocked = sorted((g["startRowIndex"], g["endRowIndex"]) for g in sm.get("merges") or []
                     if g["startColumnIndex"] < c + 1 + n and g["endColumnIndex"] > c
                     and not (g["startColumnIndex"] >= c and g["endColumnIndex"] <= c + 1)
                     # inserted columns: only a merge straddling the insert point is in the way
                     and (not insert or (g["startColumnIndex"] <= c and g["endColumnIndex"] > c + 1)))
    bands, start = [], 0
    for a, b in blocked:
        if a > start:
            bands.append((start, min(a, rows)))
        start = max(start, b)
    if start < rows:
        bands.append((start, rows))
    # never past `rows` -- a merge below max_row must not open a band down there
    # (2026-10-08: it did, and pasted over Tony Chavez's sales planner)
    bands = [(a, b) for a, b in bands if a < b and b <= rows]
    for a, b in bands:
        reqs.append({"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": a, "endRowIndex": b,
                       "startColumnIndex": c, "endColumnIndex": c + 1},
            "destination": {"sheetId": sid, "startRowIndex": a, "endRowIndex": b,
                            "startColumnIndex": c + 1, "endColumnIndex": c + 1 + n},
            "pasteType": "PASTE_NORMAL"}})
    width = ((sm.get("data") or [{}])[0].get("columnMetadata") or [{}])[0].get("pixelSize")
    if width and not max_row:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c + 1, "endIndex": c + 1 + n},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    # conditional formats that stop at the last week column now run to the new one
    for idx, rule in enumerate(sm.get("conditionalFormats") or []):
        rngs = rule.get("ranges") or []
        if any(r.get("endColumnIndex") == c + 1 for r in rngs):
            for r in rngs:
                if r.get("endColumnIndex") == c + 1:
                    r["endColumnIndex"] = c + 1 + n
            reqs.append({"updateConditionalFormatRule": {"index": idx, "sheetId": sid, "rule": rule}})
    fill._retry(sh.batch_update, {"requests": reqs})
    budget[0] -= grow * rows

    # literals: dates become their own week, anything else is cleared
    fixes, cleared = [], 0
    raw = fill._retry(ws.get_values, f"{_col_letter(c)}1:{_col_letter(c)}{rows}",
                      value_render_option="UNFORMATTED_VALUE")
    for i, cell in enumerate(src):
        v = cell[0] if cell else ""
        if v == "" or str(v).startswith("=") or any(a <= i < b for a, b in blocked):
            continue
        rv = raw[i][0] if i < len(raw) and raw[i] else v
        d = _as_date(rv)
        for k in range(1, n + 1):
            a1 = f"{_col_letter(c + k)}{i + 1}"
            if d:
                fixes.append({"range": a1, "values": [[(d + dt.timedelta(days=7 * k)).strftime("%m/%d/%Y")]]})
            else:
                fixes.append({"range": a1, "values": [[""]]})
        if not d:
            cleared += 1
    if fixes:
        fill._retry(ws.batch_update, fixes, value_input_option="USER_ENTERED")

    # verify the header chain landed on consecutive Sundays
    cols = fill.find_sunday_columns([fill._retry(ws.row_values, fill.HEADER_ROW)])
    want = [last + dt.timedelta(days=7 * k) for k in range(1, n + 1)]
    bad = [w for w in want if w not in cols]
    tail = f"; {cleared} typed value row(s) not carried" if cleared else ""
    return ("extended " + msg + tail) if not bad else f"EXTENDED BUT header missing {bad[:3]} -- check by hand"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="2027-06-27", help="last Sunday to reach (YYYY-MM-DD)")
    ap.add_argument("--only", action="append")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-row", type=int,
                    help="copy only rows 1..N (an owner's own block sits below)")
    ap.add_argument("--insert", action="store_true",
                    help="insert fresh columns after the last week (tab has its own block there)")
    args = ap.parse_args(argv)
    until = dt.date.fromisoformat(args.until)

    sh = fill.open_sheet()
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(title,gridProperties))"})
    used = sum(s["properties"]["gridProperties"]["rowCount"] * s["properties"]["gridProperties"]["columnCount"]
               for s in meta["sheets"])
    budget = [CELL_CAP - used - 50_000]  # keep headroom for new tabs
    print(f"cells {used:,} / {CELL_CAP:,}")

    tabs = [m["sheet_tab"] for m in fill.load_mapping().get("confirmed") or []]
    tabs = list(dict.fromkeys(tabs + [fill._CFG["template_tab"]]))
    if args.only:
        want = {_norm(t) for t in args.only}
        tabs = [t for t in tabs if _norm(t) in want] or args.only
    for t in tabs:
        if _norm(t) in SKIP_TABS:
            continue
        try:
            ws = fill.worksheet_ci(sh, t)
        except Exception:
            print(f"  {t}: skip: tab not found")
            continue
        try:
            print(f"  {t}: {extend_tab(sh, ws, until, dry_run=args.dry_run, budget=budget, insert=args.insert, max_row=args.max_row)}", flush=True)
        except Exception as e:
            print(f"  {t}: ERROR {str(e)[:200]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
