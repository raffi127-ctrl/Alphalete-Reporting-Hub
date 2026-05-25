"""Production Breakdown fill — combined design (NI + WIRELESS in one chart,
mixed-rep cells merged vertically).

Per tab:
  1. Find every Production Breakdown chart (anchor: 'Rep' cell with
     'Product Type (Broken Out)' to its right). 2-chart tabs get the 2nd
     chart deleted.
  2. Combined data per rep: 1 row per ptype sold (NI / WIRELESS only).
     Combined total = sum of NI + WIRELESS totals; the SAME combined total
     shows on each of a mixed rep's rows so sorting keeps them adjacent.
  3. Sort all (rep, ptype) rows by combined-total DESC, then rep name asc,
     then ptype rank (NI first).
  4. Update Total row (per-day sums + grand total NOT double-counted).
  5. Write rep+ptype rows. For mixed reps: rep name + total only on the
     1st row; blank on subsequent. ptype + per-day on every row.
  6. mergeCells: Rep cell + Product Total cell vertically across each
     mixed-rep pair. (Clears any basic filter on the tab first — basic
     filters block cross-row merges.)
  7. Format-copy from Hasani Lynch's NEW INTERNET chart (header / sub-header
     / Total / rep template tiled) — Megan-formatted source. Skipped for
     Hasani himself.
  8. Trailing-format cleanup below rep_last (clears stray borders from
     previous larger weeks), then re-draw the thick black outer border
     around the chart bounds.
  9. Zebra striping: alternate light-gray background per rep group (mixed
     pair = one group, share the same color).

The fill keys off existing rep-row content (per-rep ptype walk handles
merged-label rows correctly). Empty 'Next Promotion' template tabs OK —
Raf Hidalgo intentionally has no Production Breakdown.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import gspread

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase


SRC_TAB = "Hasani Lynch"
SRC_PTYPE = "NEW INTERNET"
ALLOWED_PTYPES = ["NEW INTERNET", "WIRELESS"]
PTYPE_RANK = {"NEW INTERNET": 0, "WIRELESS": 1}
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]
MAX_LOOK = 40
NONE_BORDER = {"style": "NONE"}
THICK_BORDER = {"style": "SOLID_THICK",
                "color": {"red": 0, "green": 0, "blue": 0}}
LIGHT_GRAY = {"red": 243/255, "green": 243/255, "blue": 243/255}

# Tabs that don't have this section by design
EXPECTED_NO_SECTION = {"Raf Hidalgo"}


# --------------------------------------------------------- crosstab parser
def parse_crosstab(path: Path) -> Dict[str, dict]:
    """Re-parses opt_personal_production.csv with the ptype + combined-total
    structure this module needs. Returns {owner_norm: {raw, rows[{rep,
    ptype, days{day:int}, total}]}}. Filters to ALLOWED_PTYPES only.
    Skips rows with total == 0."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        return {}
    headers = [str(h).strip() for h in rows[0]]
    day_cols = {d: headers.index(d) for d in DAY_ORDER if d in headers}
    total_col = headers.index("Product Total")
    owner_col = headers.index("Owner Name")
    rep_col = headers.index("Rep")
    ptype_col = headers.index("Product Type (Broken Out)")
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) < total_col + 1:
            continue
        owner = (r[owner_col] or "").strip()
        rep = (r[rep_col] or "").strip()
        ptype = (r[ptype_col] or "").strip().upper()
        if not owner or not rep or rep.lower() == "total":
            continue
        if ptype not in ALLOWED_PTYPES:
            continue
        days = {d: int(r[c].strip()) if c < len(r) and r[c].strip().isdigit() else 0
                for d, c in day_cols.items()}
        total = r[total_col].strip()
        total_n = int(total) if total.isdigit() else 0
        if total_n == 0:
            continue
        ent = out.setdefault(opt_phase._norm(owner),
                             {"raw": owner, "rows": []})
        ent["rows"].append({"rep": rep, "ptype": ptype,
                            "days": days, "total": total_n})
    return out


def find_owner(tab: str, parsed: Dict[str, dict],
               aliases_map: Dict[str, List[str]]) -> Optional[dict]:
    cands = {tab}
    for canon, al in aliases_map.items():
        if opt_phase._norm(tab) in {opt_phase._norm(canon)} | {opt_phase._norm(a) for a in al}:
            cands.update([canon] + list(al))
    for c in cands:
        ent = parsed.get(opt_phase._norm(c))
        if ent:
            return ent
    return None


# --------------------------------------------------- chart layout helpers
def find_charts(grid: List[List[str]]) -> List[Tuple[int, int]]:
    out = []
    for i, row in enumerate(grid, start=1):
        for j, v in enumerate(row, start=1):
            if v.strip() == "Rep" and j < len(row) and \
                    (row[j] if j < len(row) else "").strip() == "Product Type (Broken Out)":
                out.append((i, j))
    return out


def chart_layout(grid: List[List[str]], ar: int, ac: int) -> dict:
    """Layout for a Production Breakdown chart. The rep-row walk stops only
    when BOTH label_col AND ptype_col are blank — handles merged-label rows
    (2nd row of a mixed-rep pair)."""
    subheader_row = ar
    total_row = ar + 1
    rep_first = ar + 2
    rep_rows = []
    for off in range(0, 200):
        rr = rep_first + off
        if rr - 1 >= len(grid):
            break
        label = (grid[rr - 1][ac - 1] if ac - 1 < len(grid[rr - 1]) else "").strip()
        ptype = (grid[rr - 1][ac] if ac < len(grid[rr - 1]) else "").strip().upper()
        if not label and not ptype:
            break
        rep_rows.append({"row": rr, "rep": label, "ptype": ptype})
    rep_last = rep_rows[-1]["row"] if rep_rows else (rep_first - 1)
    ptypes = [r["ptype"] for r in rep_rows if r["ptype"]]
    detected_ptype = max(set(ptypes), key=ptypes.count) if ptypes else None
    header_row, header_col = ar - 1, None
    if header_row >= 1:
        for k, v2 in enumerate(grid[header_row - 1], start=1):
            if v2.strip().startswith("WE "):
                header_col = k
                break
    return {
        "header_row": header_row, "header_col": header_col,
        "subheader_row": subheader_row, "total_row": total_row,
        "rep_first": rep_first, "rep_last": rep_last,
        "label_col": ac, "ptype_col": ac + 1,
        "first_day_col": ac + 2, "total_col": ac + 9,
        "last_col": ac + 9,
        "rep_rows": rep_rows, "ptype": detected_ptype,
    }


def build_display_rows(owner: dict) -> List[dict]:
    """Group by rep; combined total = sum NI+WIRELESS; sort by
    -combined_total, rep name, ptype rank."""
    per_rep: Dict[str, List[dict]] = {}
    for r in owner["rows"]:
        if r["ptype"] not in ALLOWED_PTYPES:
            continue
        per_rep.setdefault(r["rep"], []).append(r)
    display = []
    for rep, ptype_rows in per_rep.items():
        combined = sum(r["total"] for r in ptype_rows)
        ptype_rows.sort(key=lambda r: PTYPE_RANK.get(r["ptype"], 99))
        for idx, r in enumerate(ptype_rows):
            display.append({
                "rep": rep, "ptype": r["ptype"], "days": r["days"],
                "combined_total": combined,
                "rep_count": len(ptype_rows),
                "first_in_pair": idx == 0,
            })
    display.sort(key=lambda r: (-r["combined_total"], r["rep"],
                                 PTYPE_RANK.get(r["ptype"], 99)))
    return display


# --------------------------------------------- API request builders
def fmt_we_header(d) -> str:
    return f"WE {d.month}.{d.day}"


def copyfmt_req(src_sid, sr1, sr2, sc1, sc2, dst_sid, dr1, dr2, dc1, dc2):
    return {"copyPaste": {
        "source": {"sheetId": src_sid,
                   "startRowIndex": sr1 - 1, "endRowIndex": sr2,
                   "startColumnIndex": sc1 - 1, "endColumnIndex": sc2},
        "destination": {"sheetId": dst_sid,
                        "startRowIndex": dr1 - 1, "endRowIndex": dr2,
                        "startColumnIndex": dc1 - 1, "endColumnIndex": dc2},
        "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}}


# --------------------------------------------- main per-tab processor
def fill_for_tab(sh, ws, parsed: Dict[str, dict],
                 aliases_map: Dict[str, List[str]],
                 src_chart: dict, src_sid: int,
                 we_sunday) -> dict:
    """Process one tab. Returns a status dict."""
    tab = ws.title
    if tab in EXPECTED_NO_SECTION:
        return {"tab": tab, "status": "EXPECTED_NO_SECTION"}
    sid = ws._properties["sheetId"]
    grid = rfill._retry(ws.get_all_values)
    anchors = find_charts(grid)
    if not anchors:
        return {"tab": tab, "status": "NO_CHART"}

    chart2_deleted = False
    if len(anchors) >= 2:
        c2 = chart_layout(grid, *anchors[1])
        del_top = c2["header_row"]
        if del_top - 2 >= 0 and del_top - 2 < len(grid):
            gap = [(grid[del_top - 2][c - 1] if c - 1 < len(grid[del_top - 2]) else "").strip()
                   for c in range(c2["label_col"], c2["last_col"] + 1)]
            if not any(gap):
                del_top -= 1
        rfill._retry(sh.batch_update, {"requests": [{
            "deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                "startIndex": del_top - 1, "endIndex": c2["rep_last"]}}}]})
        grid = rfill._retry(ws.get_all_values)
        anchors = find_charts(grid)
        chart2_deleted = True

    chart = chart_layout(grid, *anchors[0])
    owner = find_owner(tab, parsed, aliases_map)
    if not owner:
        return {"tab": tab, "status": "NO_DATA"}

    display = build_display_rows(owner)
    n_old = len(chart["rep_rows"])
    n_new = len(display)
    n_mixed = sum(1 for d in display if d["first_in_pair"] and d["rep_count"] > 1)

    # Total row
    tot_days = {d: 0 for d in DAY_ORDER}
    grand = 0
    seen = set()
    for d in display:
        for day in DAY_ORDER:
            tot_days[day] += d["days"].get(day, 0)
        if d["rep"] not in seen:
            grand += d["combined_total"]
            seen.add(d["rep"])

    # ----- data writes
    updates: List[Tuple[str, Any]] = []
    if chart["header_col"]:
        updates.append((gspread.utils.rowcol_to_a1(chart["header_row"], chart["header_col"]),
                        fmt_we_header(we_sunday)))
    tr = chart["total_row"]
    updates.append((gspread.utils.rowcol_to_a1(tr, chart["label_col"]), "Total"))
    updates.append((gspread.utils.rowcol_to_a1(tr, chart["ptype_col"]), "Total"))
    for k, day in enumerate(DAY_ORDER):
        updates.append((gspread.utils.rowcol_to_a1(tr, chart["first_day_col"] + k),
                        tot_days[day] if tot_days[day] else ""))
    updates.append((gspread.utils.rowcol_to_a1(tr, chart["total_col"]),
                    grand if grand else ""))

    rep_start = chart["total_row"] + 1
    merges_pending = []
    for k, d in enumerate(display):
        row = rep_start + k
        if d["first_in_pair"]:
            updates.append((gspread.utils.rowcol_to_a1(row, chart["label_col"]), d["rep"]))
            updates.append((gspread.utils.rowcol_to_a1(row, chart["total_col"]),
                            d["combined_total"]))
            if d["rep_count"] > 1:
                merges_pending.append((row, row + d["rep_count"] - 1, chart["label_col"]))
                merges_pending.append((row, row + d["rep_count"] - 1, chart["total_col"]))
        else:
            updates.append((gspread.utils.rowcol_to_a1(row, chart["label_col"]), ""))
            updates.append((gspread.utils.rowcol_to_a1(row, chart["total_col"]), ""))
        updates.append((gspread.utils.rowcol_to_a1(row, chart["ptype_col"]), d["ptype"]))
        for di, day in enumerate(DAY_ORDER):
            v = d["days"].get(day, 0)
            updates.append((gspread.utils.rowcol_to_a1(row, chart["first_day_col"] + di),
                            v if v else ""))

    rfill._retry(ws.batch_update,
                 [{"range": a1, "values": [[v]]} for a1, v in updates],
                 value_input_option="USER_ENTERED")

    # ----- delete leftover rep rows
    extra = max(0, n_old - n_new)
    if extra:
        rfill._retry(sh.batch_update, {"requests": [{
            "deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                "startIndex": rep_start + n_new - 1,
                "endIndex": rep_start + n_old - 1}}}]})

    # Unmerge the WHOLE rep area before (re)merging. Without this, a rep whose
    # row-shape changed since last run leaves a stale merge that the new range
    # PARTIAL-overlaps, which Sheets rejects with [400] "you must select all
    # cells in a merged range to merge or unmerge them" — the 2026-05-25 bug
    # that errored 32 reps. Unmerging the entire rep area fully contains any
    # stale merge, so the re-merge can never partial-overlap. Computed once,
    # used at both merge points below.
    _unmerge_reqs = [{"unmergeCells": {"range": {"sheetId": sid,
        "startRowIndex": rep_start - 1,
        "endRowIndex": rep_start + len(display) - 1,
        "startColumnIndex": c - 1, "endColumnIndex": c}}}
        for c in (chart["label_col"], chart["total_col"])] if merges_pending else []

    # ----- mergeCells for mixed reps (clear filter + stale merges first)
    if merges_pending:
        try:
            rfill._retry(sh.batch_update,
                         {"requests": [{"clearBasicFilter": {"sheetId": sid}}]})
        except Exception:
            pass
        merge_reqs = [{"mergeCells": {
            "range": {"sheetId": sid,
                      "startRowIndex": top - 1, "endRowIndex": bot,
                      "startColumnIndex": col - 1, "endColumnIndex": col},
            "mergeType": "MERGE_ALL"}} for top, bot, col in merges_pending]
        rfill._retry(sh.batch_update, {"requests": _unmerge_reqs + merge_reqs})

    # ----- re-find chart, format-copy (skip Hasani), trailing cleanup,
    # outer border, zebra striping
    grid = rfill._retry(ws.get_all_values)
    chart = chart_layout(grid, *find_charts(grid)[0])
    rl = chart["rep_last"]
    last_col = chart["last_col"]
    fmt_status = "skip-self"

    post_reqs: List[dict] = []
    if tab != SRC_TAB:
        sc1, sc2 = src_chart["label_col"], src_chart["last_col"]
        dc1, dc2 = chart["label_col"], chart["last_col"]
        post_reqs += [
            copyfmt_req(src_sid, src_chart["header_row"], src_chart["header_row"],
                        sc1, sc2, sid, chart["header_row"], chart["header_row"], dc1, dc2),
            copyfmt_req(src_sid, src_chart["subheader_row"], src_chart["subheader_row"],
                        sc1, sc2, sid, chart["subheader_row"], chart["subheader_row"], dc1, dc2),
            copyfmt_req(src_sid, src_chart["total_row"], src_chart["total_row"],
                        sc1, sc2, sid, chart["total_row"], chart["total_row"], dc1, dc2),
            copyfmt_req(src_sid, src_chart["rep_first"], src_chart["rep_first"],
                        sc1, sc2, sid, chart["rep_first"], rl, dc1, dc2),
        ]
        fmt_status = "copied"

    # Trailing cleanup + outer border
    post_reqs += [
        {"updateBorders": {
            "range": {"sheetId": sid,
                "startRowIndex": rl, "endRowIndex": rl + MAX_LOOK,
                "startColumnIndex": chart["label_col"] - 1, "endColumnIndex": last_col},
            "top": NONE_BORDER, "bottom": NONE_BORDER,
            "left": NONE_BORDER, "right": NONE_BORDER,
            "innerHorizontal": NONE_BORDER, "innerVertical": NONE_BORDER}},
        {"repeatCell": {
            "range": {"sheetId": sid,
                "startRowIndex": rl, "endRowIndex": rl + MAX_LOOK,
                "startColumnIndex": chart["label_col"] - 1, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat"}},
        {"updateBorders": {
            "range": {"sheetId": sid,
                "startRowIndex": chart["header_row"] - 1, "endRowIndex": rl,
                "startColumnIndex": chart["label_col"] - 1, "endColumnIndex": last_col},
            "top": THICK_BORDER, "bottom": THICK_BORDER,
            "left": THICK_BORDER, "right": THICK_BORDER}},
    ]

    # PASTE_FORMAT unmerges destination cells as a side effect, so the
    # mergeCells we sent above don't survive past_reqs. Re-apply merges AFTER.
    rfill._retry(sh.batch_update, {"requests": post_reqs})
    if merges_pending:
        merge_reqs = [{"mergeCells": {
            "range": {"sheetId": sid,
                      "startRowIndex": top - 1, "endRowIndex": bot,
                      "startColumnIndex": col - 1, "endColumnIndex": col},
            "mergeType": "MERGE_ALL"}} for top, bot, col in merges_pending]
        # Same unmerge-first guard (post_reqs' PASTE_FORMAT can leave/re-create
        # merges that would otherwise partial-overlap the re-merge).
        rfill._retry(sh.batch_update, {"requests": _unmerge_reqs + merge_reqs})

    # Zebra striping: alternate per rep group (mixed pair = 1 group)
    groups = []
    i = 0
    while i < len(display):
        if i + 1 < len(display) and display[i]["first_in_pair"] and display[i]["rep_count"] > 1:
            groups.append((rep_start + i, rep_start + i + display[i]["rep_count"] - 1))
            i += display[i]["rep_count"]
        else:
            groups.append((rep_start + i, rep_start + i))
            i += 1
    stripe_reqs = []
    for idx, (top, bot) in enumerate(groups):
        if idx % 2 == 1:
            stripe_reqs.append({"repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": top - 1, "endRowIndex": bot,
                          "startColumnIndex": chart["label_col"] - 1, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {"backgroundColor": LIGHT_GRAY}},
                "fields": "userEnteredFormat.backgroundColor"}})
    if stripe_reqs:
        rfill._retry(sh.batch_update, {"requests": stripe_reqs})

    return {"tab": tab, "status": "OK", "n_rows": n_new,
            "n_reps": len({d["rep"] for d in display}),
            "n_mixed": n_mixed, "chart2_deleted": chart2_deleted,
            "fmt": fmt_status, "extra_deleted": extra}
