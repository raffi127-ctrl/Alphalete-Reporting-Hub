"""Colour the internet-mix metric rows red when they fall under target
(Raf 2026-07-17, one-on-ones).

Raf watches these AT&T mix rates on the ICD one-on-ones and wants any week under
90% to jump out. AT&T is pressing on them, so the number has to read at a glance.

DELIBERATELY NOT a Google Sheets "conditional format" rule. A CF rule pins itself
to a grid range (row 27, cols C:DF) — and these tabs get rows inserted and moved
constantly, so a pinned rule silently ends up colouring the WRONG row. Instead we
re-read the sheet on every run: find the rows by their column-B LABEL, read each
week cell's actual value, and set that cell's colour from what's there. Rows can
move anywhere between runs and the colours still land correctly (Megan 2026-07-17:
"read the cell each time and apply the correct colors — cells/rows change all the
time").

Rows coloured (found by label, never a hardcoded row number):
  - 1 GIG %   red under 90%
  - ABP%      red under 90%
  - 5 GIG %   red under 90%

The cell is HIGHLIGHTED (background), not re-coloured text. Each row's normal
background is derived from the row itself, so a cell that recovers above target
goes back to whatever shading its template uses instead of being blanked white.

Blank cells are left alone on purpose: a blank mix rate means "no qualifying
internet sales that week" = N/A, not a 0% failure ([[1 GIG% blank = N/A]] rule).
The "-%" no-data marker is likewise never highlighted.

Run:
  .venv/bin/python -m automations.recruiting_report.metric_thresholds --only "Marcellus Butler" --dry-run
  .venv/bin/python -m automations.recruiting_report.metric_thresholds --only "Marcellus Butler"
  .venv/bin/python -m automations.recruiting_report.metric_thresholds --all
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Dict, List, Optional, Tuple

import gspread

from . import fill

# Sheet row label -> threshold in PERCENT POINTS (90 = 90%). Under this, red.
THRESHOLD_ROWS: Dict[str, float] = {
    "1 GIG %": 90.0,
    "ABP%":    90.0,
    "5 GIG %": 90.0,
}

# The cell gets HIGHLIGHTED — background only (Megan 2026-07-17: "the rows should
# get highlighted not the text color changed"). Light enough that the existing
# black value stays readable, saturated enough to read as red against the
# template's mauve row shading.
_RED_BG = {"red": 0.878, "green": 0.400, "blue": 0.400}   # #E06666
_WHITE_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}

# ONLY the background. Text formatting is deliberately left alone: the OPT fill
# red-fonts any impossible percentage (>100%) via shared/sheet_flags, and this
# pass runs after it — touching textFormat here would silently undo that flag.
_FIELDS = "userEnteredFormat.backgroundColor"


def _norm(s) -> str:
    """Match fill/opt_phase normalization: lowercase, drop apostrophes/periods,
    collapse whitespace, drop spaces around / - %."""
    s = str(s or "").strip().lower()
    s = s.replace("'", "").replace("’", "").replace(".", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([/\-%])\s*", r"\1", s)
    return s


_NORM_THRESHOLDS = {_norm(k): v for k, v in THRESHOLD_ROWS.items()}
_NORM_LABELS = {_norm(k): k for k in THRESHOLD_ROWS}


def _find_metric_rows(col_b: List[str]) -> Dict[str, int]:
    """{normalized label: FIRST 1-indexed row} for the threshold labels present
    in column B. First occurrence wins, matching _opt_block_rows' setdefault —
    so the live OPT-cluster row gets coloured, not a stale duplicate lower down."""
    out: Dict[str, int] = {}
    for j, v in enumerate(col_b):
        nv = _norm(v)
        if nv in _NORM_THRESHOLDS and nv not in out:
            out[nv] = j + 1
    return out


def _pct(cell: str) -> Optional[float]:
    """The cell's value in percent points ('87%' -> 87.0). None when the cell is
    blank, the '-%' no-data marker, or anything non-numeric — those never get
    coloured."""
    t = str(cell or "").strip().replace(",", "").replace("%", "")
    if not t or t == "-":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _runs(cols: List[int], is_red: Dict[int, bool]) -> List[Tuple[int, int, bool]]:
    """Collapse consecutive columns sharing a state into (start, end, red) runs,
    so a row becomes a handful of range writes instead of one per week."""
    out: List[Tuple[int, int, bool]] = []
    for c in cols:
        state = is_red[c]
        if out and out[-1][2] == state and out[-1][1] == c - 1:
            out[-1] = (out[-1][0], c, state)
        else:
            out.append((c, c, state))
    return out


def _rgb(bg: Optional[dict]) -> Tuple[float, float, float]:
    """A backgroundColor dict as a comparable triple. Absent = default white."""
    bg = bg or {}
    return (round(bg.get("red", 0.0), 3), round(bg.get("green", 0.0), 3),
            round(bg.get("blue", 0.0), 3))


_RED_RGB = _rgb(_RED_BG)


def _is_red(bg: Optional[dict]) -> bool:
    """Is this cell already carrying our highlight? Compared with a tolerance —
    Sheets snaps colours to 8-bit, so 0.878 comes back as 0.8745098 and an exact
    match would miss. Getting this wrong would let a mostly-red row adopt red as
    its own 'normal' background and never clear."""
    return all(abs(a - b) < 0.02 for a, b in zip(_rgb(bg), _RED_RGB))


def _quote_tab(t: str) -> str:
    return t.replace("'", "''")


def _row_backgrounds(sh, tab_name: str, rows: List[int], last_col: int
                     ) -> Dict[int, List[Optional[dict]]]:
    """{row: [backgroundColor per column, 1..last_col]} for the given rows."""
    if not rows:
        return {}
    end = gspread.utils.rowcol_to_a1(1, last_col).rstrip("0123456789")
    ranges = [f"'{_quote_tab(tab_name)}'!A{r}:{end}{r}" for r in rows]
    meta = fill._retry(
        sh.fetch_sheet_metadata,
        params={"ranges": ranges,
                "fields": "sheets(data(rowData(values(userEnteredFormat("
                          "backgroundColor)))))"},
    )
    out: Dict[int, List[Optional[dict]]] = {}
    data = (meta.get("sheets") or [{}])[0].get("data", [])
    for r, block in zip(rows, data):
        rd = block.get("rowData") or [{}]
        vals = (rd[0] or {}).get("values", []) if rd else []
        out[r] = [v.get("userEnteredFormat", {}).get("backgroundColor")
                  for v in vals]
    return out


def _base_bg(bgs: List[Optional[dict]], week_cols: List[int]) -> dict:
    """The row's own normal background — the colour a NOT-highlighted week cell
    should carry. Taken as the most common background across the row's week
    cells, ignoring any that are already our highlight. Derived per row rather
    than assumed, because the templates differ (some metric rows are shaded, some
    are plain white, and the column-B label can be styled differently from the
    data cells). If every week cell is currently highlighted there's nothing to
    infer from, so fall back to plain white."""
    counts: Dict[Tuple[float, float, float], int] = {}
    keep: Dict[Tuple[float, float, float], dict] = {}
    for c in week_cols:
        bg = bgs[c - 1] if c - 1 < len(bgs) else None
        if _is_red(bg):
            continue
        key = _rgb(bg)
        counts[key] = counts.get(key, 0) + 1
        keep.setdefault(key, bg or _WHITE_BG)
    if not counts:
        return _WHITE_BG
    return keep[max(counts, key=counts.get)]


def _legacy_rule_deletes(sh, sheet_id: int) -> List[dict]:
    """Delete requests for any pinned CUSTOM_FORMULA rule a previous version of
    this module installed. They anchor to a fixed grid range and drift when rows
    move — that's exactly what this module replaced."""
    try:
        meta = fill._retry(
            sh.fetch_sheet_metadata,
            params={"fields": "sheets(properties.sheetId,conditionalFormats)"},
        )
    except Exception:
        return []
    idxs: List[int] = []
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != sheet_id:
            continue
        for i, rule in enumerate(s.get("conditionalFormats", [])):
            cond = rule.get("booleanRule", {}).get("condition", {})
            if cond.get("type") != "CUSTOM_FORMULA":
                continue
            formula = " ".join(v.get("userEnteredValue", "")
                               for v in cond.get("values", []))
            if "ISNUMBER" in formula:
                idxs.append(i)
    # highest index first so earlier indexes stay valid as we delete
    return [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}}
            for i in sorted(idxs, reverse=True)]


def recolor_for_tab(sh: gspread.Spreadsheet, tab_name: str,
                    dry_run: bool = False, ws=None,
                    grid: Optional[List[List[str]]] = None) -> List[str]:
    """Re-read one ICD tab and colour its mix-rate rows from the values actually
    in the cells. Safe to run any number of times. `ws`/`grid` let a caller that
    already fetched them (the Monday fill) avoid re-reading."""
    if ws is None:
        try:
            ws = fill._retry(sh.worksheet, tab_name)
        except Exception as e:
            return [f"[SKIP] {tab_name}: tab not found ({e})"]
    if grid is None:
        grid = fill._retry(ws.get_all_values)
    if not grid:
        return [f"[SKIP] {tab_name}: empty tab"]

    col_b = [r[1] if len(r) > 1 else "" for r in grid]
    rows = _find_metric_rows(col_b)
    if not rows:
        return [f"[SKIP] {tab_name}: none of {list(THRESHOLD_ROWS)} on tab"]
    week_cols = sorted(fill.find_sunday_columns(grid, header_row_idx=0).values())
    if not week_cols:
        return [f"[SKIP] {tab_name}: no weekly date columns found"]

    requests: List[dict] = []
    notes: List[str] = []
    sheet_id = ws.id
    ordered = sorted(rows.items(), key=lambda kv: kv[1])
    # Existing backgrounds are only needed to build the write, so a dry run
    # skips the fetch entirely (halves its API calls across ~74 tabs).
    bg_by_row = ({} if dry_run else
                 _row_backgrounds(sh, ws.title, [r for _, r in ordered],
                                  week_cols[-1]))
    for nv, r in ordered:
        limit = _NORM_THRESHOLDS[nv]
        row_vals = grid[r - 1] if r - 1 < len(grid) else []
        base = _base_bg(bg_by_row.get(r, []), week_cols)
        is_red: Dict[int, bool] = {}
        reds: List[str] = []
        for c in week_cols:
            v = _pct(row_vals[c - 1] if c - 1 < len(row_vals) else "")
            red = v is not None and v < limit
            is_red[c] = red
            if red:
                reds.append(f"{gspread.utils.rowcol_to_a1(r, c)}={v:g}%")
        for c0, c1, red in _runs(week_cols, is_red):
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": r - 1, "endRowIndex": r,
                          "startColumnIndex": c0 - 1, "endColumnIndex": c1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _RED_BG if red else base}},
                "fields": _FIELDS,
            }})
        notes.append(f"{_NORM_LABELS[nv]} (row {r}): {len(reds)} under "
                     f"{limit:g}%" + (f" -> {', '.join(reds[-4:])}" if reds else ""))

    if dry_run:
        return [f"[DRY-RUN] {tab_name}: would recolour {len(rows)} row(s)"] + \
               [f"    {n}" for n in notes]

    requests = _legacy_rule_deletes(sh, sheet_id) + requests
    fill._retry(sh.batch_update, {"requests": requests})
    return [f"[OK] {tab_name}: recoloured {len(rows)} row(s)"] + \
           [f"    {n}" for n in notes]


# Rows to guarantee exist, in the order they should read, ending at the anchor
# row we position against.
_WANT_ROWS = ["ABP%", "5 GIG %"]
_ANCHOR_LABEL = "1 GIG %"


def ensure_rows_for_tab(sh: gspread.Spreadsheet, tab_name: str,
                        dry_run: bool = False) -> List[str]:
    """Make sure ABP% and 5 GIG % exist directly above the Office-Metrics
    '1 GIG %' row, so the OPT fill has somewhere to put them.

    Only touches tabs that actually carry the section (an 'Office Metrics'
    header with a '1 GIG %' under it) — that structural test is what separates
    the ICD tabs from the Country boards, templates and scratch tabs, with no
    hardcoded tab list. Inserts rows; never deletes or reorders anything."""
    try:
        ws = fill._retry(sh.worksheet, tab_name)
    except Exception as e:
        return [f"[SKIP] {tab_name}: tab not found ({e})"]
    grid = fill._retry(ws.get_all_values)
    if not grid:
        return [f"[SKIP] {tab_name}: empty tab"]
    col_b = [r[1] if len(r) > 1 else "" for r in grid]

    om = next((i + 1 for i, v in enumerate(col_b)
               if _norm(v) == "office metrics"), None)
    if om is None:
        return [f"[SKIP] {tab_name}: no Office Metrics section"]
    anchor = next((i + 1 for i, v in enumerate(col_b)
                   if i + 1 > om and _norm(v) == _norm(_ANCHOR_LABEL)), None)
    if anchor is None:
        return [f"[SKIP] {tab_name}: no '{_ANCHOR_LABEL}' under Office Metrics"]

    have = {_norm(v) for v in col_b}
    missing = [lbl for lbl in _WANT_ROWS if _norm(lbl) not in have]
    if not missing:
        return [f"[OK] {tab_name}: already has {', '.join(_WANT_ROWS)}"]

    if dry_run:
        return [f"[DRY-RUN] {tab_name}: would insert {missing} above "
                f"'{_ANCHOR_LABEL}' (row {anchor})"]

    # inheritFromBefore=False -> copy styling from the metric row BELOW (the
    # 1 GIG % row), not from the section header above it.
    fill._retry(sh.batch_update, {"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": anchor - 1, "endIndex": anchor - 1 + len(missing)},
        "inheritFromBefore": False}}]})
    ups = [{"range": gspread.utils.rowcol_to_a1(anchor + i, 2),
            "values": [[lbl]]} for i, lbl in enumerate(missing)]
    fill._retry(ws.batch_update, ups, value_input_option="USER_ENTERED")
    return [f"[OK] {tab_name}: inserted {missing} at row {anchor}"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="one tab title (default: Marcellus Butler)")
    ap.add_argument("--all", action="store_true", help="every tab in the workbook")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--add-rows", action="store_true",
                    # %% — argparse %-formats help strings
                    help="insert missing ABP%% / 5 GIG %% rows before recolouring")
    args = ap.parse_args(argv)

    sh = fill.open_by_key(fill.SPREADSHEET_ID)
    if args.all:
        tabs = [ws.title for ws in fill._retry(sh.worksheets)]
    else:
        tabs = [args.only or "Marcellus Butler"]

    for t in tabs:
        if args.add_rows:
            for line in ensure_rows_for_tab(sh, t, dry_run=args.dry_run):
                print(line)
        for line in recolor_for_tab(sh, t, dry_run=args.dry_run):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
