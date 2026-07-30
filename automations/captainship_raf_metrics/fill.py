"""Sheet writer for Rafael's three captainship metric tabs.

TAB LAYOUT (the 'Captainship - Cancel Rate' tab; the other two are identical
apart from their col-A labels):

    A1  CANCEL RATE 0-30 DAYS   B1:C1  Thu 7/30/26   <- date, MERGED over the pair
    A2  Captainship Avg         B2  7.5%    C2  303
    A3  Rep                     B3  %       C3  units
    A4  Rafael Hidalgo          B4  5.7%    C4  43
    ...                                              <- one row per ICD owner
    (blank spacer rows)
    A27 CANCEL RATE 30-60 DAYS  B27:C27 Thu 7/30/26
    ...

TWO columns per day (% + count), newest in B, history growing right — the same
grammar as the churn / ABP tabs in this workbook, and the reason this module
exists instead of reusing the fiber captains' single-column writers.

EACH DAILY RUN
  1. Grow the grid if it is running out of columns.
  2. Insert a fresh B:C pair (skipped when B already carries today's date — a
     re-run then refreshes today's values in place; --force-insert overrides).
  3. Give every ICD owner Tableau has data for a row, using the blank roster
     rows Eve left under each box before inserting any.
  4. Write the date, the Captainship Avg and every owner's % + count.
  5. Re-merge the date across B:C and RE-STAMP the pair's formatting.

WHY STEP 5 STAMPS INSTEAD OF COPYING YESTERDAY'S FORMAT
The obvious move — insert, then copyPaste PASTE_FORMAT from the pair that just
shifted to D:E — is what the ABP tab did, and it drifts. Sheets stores a border
once for the two cells that share it, so painting a thick edge on C silently
clears D's left edge; the next day's copy inherits the cleared version, and the
grid degrades a little every morning until someone re-formats by hand. Stamping
the canonical style from STYLE below is drift-proof: every day's pair comes out
byte-identical, no matter what the previous one looked like.

Rows are found by their column-A LABEL and days by the date header — no
hardcoded indices (the second box sits at a different row on every tab, and one
new ICD moves it).
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Optional

from automations.recruiting_report.fill import open_by_key, _retry
from automations.shared import sheet_style as _style
from automations.captainship_raf_metrics import boxes as B

# Keep this much empty room to the right so a daily insert never pushes the
# oldest column off the edge of the grid (Sheets drops it silently).
MIN_SPARE_COLS = 8
GROW_COLS_BY = 40

_WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# ---------------------------------------------------------------------------
# House style, read off the tabs Eve set up (2026-07-30) and re-stamped onto
# every new day column. Change a value here and the whole history can be healed
# with `run.py --reformat`.
#
# NOTE ON THE PERCENT PATTERN: Eve's empty template carried '0%', which would
# round a 7.5% cancel rate to '8%' and hide a day's movement. '0.0%' matches
# both the precision Tableau prints and the sibling ABP tab. One constant.
PCT_PATTERN = "0.0%"
COUNT_PATTERN = "#,##0"
DATE_PATTERN = "ddd m/d/yy"
FONT = "Calibri"
FONT_SIZE = 13

DARK_GREEN = {"red": 0.12941177, "green": 0.27058825, "blue": 0.21568628}
LIGHT_GREEN = {"red": 0.85490197, "green": 0.9490196, "blue": 0.8156863}
BLACK = _style.BLACK
WHITE = _style.WHITE

_bd = _style.borders


def _cell(bg, borders, *, bold=False, white=False, number=None,
          wrap=False) -> dict:
    return _style.cell(bg=bg, borders=borders, font=FONT, size=FONT_SIZE,
                       bold=bold, fg=WHITE if white else None,
                       number=number, wrap=wrap)


_PCT_FMT = {"type": "PERCENT", "pattern": PCT_PATTERN}
_COUNT_FMT = {"type": "NUMBER", "pattern": COUNT_PATTERN}
_DATE_FMT = {"type": "DATE", "pattern": DATE_PATTERN}

# row class -> (format for col B, format for col C)
def _merge_edges(pair) -> dict:
    """The two-column style collapsed onto ONE column: keep the % cell's look
    but take the units cell's right-hand edge, so a single-column day is still
    bracketed by the same thick line the pair was."""
    b, c = pair
    fmt = {k: v for k, v in b.items()}
    fmt["borders"] = dict(b["borders"])
    if "right" in c["borders"]:
        fmt["borders"]["right"] = c["borders"]["right"]
    return fmt


STYLE = {
    # The date bar: dark green, white bold, boxed in thick on all four sides.
    "header": (
        _cell(DARK_GREEN, _bd(top="SOLID_THICK", bottom="SOLID_THICK",
                              left="SOLID_THICK", right="SOLID_THICK"),
              bold=True, white=True, number=_DATE_FMT),
        _cell(DARK_GREEN, _bd(top="SOLID_THICK", bottom="SOLID_THICK",
                              left="SOLID_THICK", right="SOLID_THICK"),
              bold=True, white=True),
    ),
    # Captainship Avg: the % sits on white, its count shares the pale green of
    # the label in column A.
    "avg": (
        _cell(WHITE, _bd(bottom="SOLID", left="SOLID", right="SOLID"),
              number=_PCT_FMT),
        _cell(LIGHT_GREEN, _bd(bottom="SOLID_MEDIUM", left="SOLID_MEDIUM",
                               right="SOLID_THICK"),
              bold=True, number=_COUNT_FMT),
    ),
    # The '% | units' label row: black, white text.
    "rep_header": (
        _cell(BLACK, _bd(top="SOLID_MEDIUM", bottom="SOLID_MEDIUM",
                         left="SOLID_THICK", right="SOLID_MEDIUM"),
              white=True, wrap=True),
        _cell(BLACK, _bd(top="SOLID_MEDIUM", bottom="SOLID_MEDIUM",
                         left="SOLID_MEDIUM", right="SOLID_THICK"),
              white=True, number=_COUNT_FMT),
    ),
    "rep": (
        _cell(WHITE, _bd(bottom="SOLID", left="SOLID", right="SOLID"),
              number=_PCT_FMT),
        _cell(WHITE, _bd(top="SOLID_MEDIUM", bottom="SOLID_MEDIUM",
                         left="SOLID_MEDIUM", right="SOLID_THICK"),
              number=_COUNT_FMT),
    ),
}

_FORMAT_FIELDS = _style.FORMAT_FIELDS


# ------------------------------------------------------------------ helpers
def _norm(s: str) -> str:
    """Match key for names AND labels: uppercase, trimmed, inner whitespace
    (including the newline inside 'ACTIVATION RATE\\n0-30 DAYS') collapsed."""
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def _date_label(today: dt.date) -> str:
    """'Thu 7/30/26' — how these cells render. Built by hand because %-m/%-d
    are glibc-only and this has to run on Windows too."""
    return (f"{_WEEKDAY_SHORT[today.weekday()]} "
            f"{today.month}/{today.day}/{today.year % 100}")


def open_ws(tab: str, sheet_id: Optional[str] = None, *, logfn=print):
    """The worksheet, by TITLE — falling back to its gid if it was renamed.

    Title first because a gid is meaningless in a duplicated workbook. The gid
    fallback exists because these tabs are new and Eve renames them while she
    builds; a rename should cost a log line, not a day of data."""
    sh = open_by_key(sheet_id or B.SHEET_ID)
    try:
        return sh.worksheet(tab)
    except Exception:  # noqa: BLE001 — gspread raises WorksheetNotFound
        gid = B.TAB_GIDS.get(tab)
        if gid is None or (sheet_id and sheet_id != B.SHEET_ID):
            raise
        ws = sh.get_worksheet_by_id(gid)
        logfn(f"  ℹ '{tab}' was renamed to '{ws.title}' — matched on gid {gid}. "
              f"Update boxes.py so the log stops saying this.")
        return ws


def _detect_col_step(labels: list, any_header_merged: bool) -> int:
    """How many columns one day occupies on this TAB: 2 (% + units) or 1 (%).

    READ OFF THE TAB, never assumed. Eve set these tabs up with a units column
    and then dropped it from two of them on 2026-07-30 — a report that hardcodes
    the pair would have written counts into the previous day's percentages the
    next morning.

    `labels` is the cell in column C of each box's 'Rep' row: 'units' means the
    tab is paired, '%' means C already holds the PREVIOUS day. One grid, one
    layout, so a single decisive label settles the whole tab; a box that hasn't
    been labelled yet (Eve's fresh ABP box) simply doesn't vote. With no vote at
    all, a date merged across B:C is the fallback.
    """
    votes = {_norm(x) for x in labels}
    if "UNITS" in votes:
        return 2
    if "%" in votes:
        return 1
    return 2 if any_header_merged else 1


# ---------------------------------------------------------------- structure
def _declared_tab(ws) -> str:
    """Which entry in boxes.py this worksheet IS, even after a rename — its
    title if we know it, else the tab whose gid matches. Falls through to the
    live title in a duplicated workbook, where gids are re-assigned."""
    if ws.title in B.TAB_GIDS:
        return ws.title
    for title, gid in B.TAB_GIDS.items():
        if gid == ws.id:
            return title
    return ws.title


def find_boxes(ws) -> dict:
    """Locate every box on `ws` by its col-A label.

    Returns {box key: {header_row, office_avg_row, rep_header_row, rep_rows}} —
    the shape every other captainship report uses, so daily_box_render and the
    shared row helpers accept it unchanged. `rep_rows` is keyed by NORMALIZED
    owner name.
    """
    specs = B.for_tab(_declared_tab(ws))
    grid = _retry(ws.get_all_values)
    col_a = [(r[0] if r else "") for r in grid]
    n_rows = max(len(col_a), ws.row_count)

    def _cell(row: int, col_0: int) -> str:
        r = grid[row - 1] if row - 1 < len(grid) else []
        return r[col_0] if col_0 < len(r) else ""

    merged_header_rows = {
        m["startRowIndex"] + 1
        for m in _merges(ws)
        if m.get("startColumnIndex") == 1 and m.get("endColumnIndex") == 3
    }

    found: dict = {}
    for i, label in enumerate(col_a):
        norm = _norm(label)
        if not norm:
            continue
        for spec in specs:
            if spec.box in found:
                continue
            if all(m in norm for m in spec.markers):
                found[spec.box] = i + 1        # 1-indexed sheet row
                break

    out: dict = {}
    ordered = sorted(found.items(), key=lambda kv: kv[1])
    for idx, (box, header_row) in enumerate(ordered):
        end_row = (ordered[idx + 1][1] - 1
                   if idx + 1 < len(ordered) else n_rows)

        # 'Captainship Avg' and 'Rep' by LABEL, never by +1/+2 — one manual row
        # insert would otherwise point the writer at a real owner's row.
        avg_row = rep_header_row = None
        for r in range(header_row + 1, min(end_row, len(col_a)) + 1):
            norm = _norm(col_a[r - 1])
            if norm == "REP":
                rep_header_row = r
                break
            if avg_row is None and "AVG" in norm:
                avg_row = r
        if rep_header_row is None:
            rep_header_row = header_row + 2
        if avg_row is None:
            avg_row = header_row + 1

        rep_rows: dict = {}
        for r in range(rep_header_row + 1, min(end_row, len(col_a)) + 1):
            name = col_a[r - 1].strip()
            if not name:
                continue
            norm = _norm(name)
            if norm == "REP" or "AVG" in norm:
                continue
            rep_rows[norm] = r

        out[box] = {
            "header_row": header_row,
            "office_avg_row": avg_row,
            "avg_row": avg_row,          # both spellings; readers differ
            "rep_header_row": rep_header_row,
            "rep_rows": rep_rows,
            "end_row": end_row,
        }

    step = _detect_col_step(
        [_cell(s["rep_header_row"], 2) for s in out.values()],
        any(s["header_row"] in merged_header_rows for s in out.values()))
    for s in out.values():
        s["col_step"] = step
    return out


def _merges(ws) -> list:
    """This tab's merge ranges (empty on any failure — a missing merge must
    never cost us the run, the label check above is the primary signal)."""
    try:
        meta = ws.spreadsheet.fetch_sheet_metadata(
            {"fields": "sheets(properties(sheetId),merges)"})
    except Exception:  # noqa: BLE001
        return []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == ws.id:
            return s.get("merges") or []
    return []


def col_step(boxes: dict) -> int:
    """Columns per day on this tab — every box on a tab shares one layout."""
    return next(iter(boxes.values()), {}).get("col_step", 2) if boxes else 2


def ensure_columns(ws, *, dry_run: bool = False, logfn=print) -> None:
    """Append columns when the grid is nearly full. Two go in per day, so
    without this the oldest pair would fall off the right edge and be lost."""
    grid = _retry(ws.get_all_values)
    used = max((len(r) for r in grid), default=0)
    if ws.col_count - used >= MIN_SPARE_COLS:
        return
    if dry_run:
        logfn(f"  (dry-run) would grow the grid {ws.col_count} -> "
              f"{ws.col_count + GROW_COLS_BY} columns ({used} in use)")
        return
    logfn(f"  Growing grid: {ws.col_count} -> {ws.col_count + GROW_COLS_BY} "
          f"columns ({used} in use)")
    ws.spreadsheet.batch_update({"requests": [{
        "appendDimension": {"sheetId": ws.id, "dimension": "COLUMNS",
                            "length": GROW_COLS_BY}}]})
    time.sleep(1)


def today_already_filled(ws, boxes: dict, today: dt.date) -> bool:
    """True when B of any box header already shows today — an earlier run has
    opened the day's pair and a second insert would leave a blank duplicate."""
    if not boxes:
        return False
    want = _date_label(today)
    rows = sorted({s["header_row"] for s in boxes.values()})
    for got in _retry(ws.batch_get, [f"B{r}" for r in rows]):
        val = (got[0][0] if got and got[0] else "")
        if (val or "").strip() == want:
            return True
    return False


def insert_day_at_b(ws, step: int, *, dry_run: bool = False,
                    logfn=print) -> None:
    """Open today's column(s) — a B:C pair, or just B on a tab with no units
    column. Whole-column insert, so the merges on the box header rows shift
    right intact and nothing above the first box can drift.

    inheritFromBefore=False deliberately: the new day comes in unformatted and
    UNVALUED, and format_pair() stamps the house style onto it. Copying
    yesterday's format is what let the ABP tab's borders rot (see the module
    docstring)."""
    if dry_run:
        logfn(f"  (dry-run) would insert {step} fresh column(s) at B")
        return
    ws.spreadsheet.batch_update({"requests": [{
        "insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 1 + step},
            "inheritFromBefore": False,
        }}]})
    time.sleep(2)


# ------------------------------------------------------------------- roster
def place_reps(ws, boxes: dict, parsed: dict, *, dry_run: bool = False,
               logfn=print) -> dict:
    """Give every ICD owner with data today a row in each box.

    Eve leaves blank roster rows under each box; those are used first (a name is
    simply written into one) and only when they run out is a row INSERTED. That
    keeps the tab's own spacing instead of pushing the second box down the first
    time 15 owners arrive on a tab laid out for 23.

    Returns {box: [names added]} and updates `boxes` in place.
    """
    reps = parsed.get("reps", {})
    if not reps:
        return {}

    plans: list = []
    added: dict = {}
    # Bottom box first: an insert in the top box moves every row below it, and
    # planning upwards keeps the captured row numbers valid while we build.
    for box, sect in sorted(boxes.items(),
                            key=lambda kv: kv[1]["header_row"], reverse=True):
        have = set(sect["rep_rows"])
        missing = sorted(n for n, per_box in reps.items()
                         if _norm(n) not in have
                         and (per_box.get(box) or {}).get("pct"))
        if not missing:
            continue
        anchor = (max(sect["rep_rows"].values()) if sect["rep_rows"]
                  else sect["rep_header_row"])
        free = max(sect["end_row"] - anchor, 0)
        n_insert = max(len(missing) - free, 0)
        plans.append({"box": box, "anchor": anchor, "names": missing,
                      "insert": n_insert})
        added[box] = missing

    if not plans:
        return {}
    if dry_run:
        for p in plans:
            logfn(f"  (dry-run) would add {len(p['names'])} ICD row(s) to "
                  f"{p['box']} at row {p['anchor'] + 1} "
                  f"({p['insert']} row insert(s) needed): {p['names']}")
        return added

    inserts = [p for p in plans if p["insert"]]
    if inserts:
        ws.spreadsheet.batch_update({"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": p["anchor"],
                          "endIndex": p["anchor"] + p["insert"]},
                "inheritFromBefore": True,
            }} for p in inserts]})
        time.sleep(1)

    def _shift_above(anchor: int) -> int:
        return sum(p["insert"] for p in inserts if p["anchor"] < anchor)

    cells = []
    for p in plans:
        base = p["anchor"] + _shift_above(p["anchor"])
        for i, name in enumerate(p["names"]):
            cells.append({"range": f"'{ws.title}'!A{base + 1 + i}",
                          "values": [[name]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "RAW", "data": cells})

    # Re-resolve every row index the inserts pushed down.
    for p in sorted(inserts, key=lambda x: x["anchor"]):
        delta = p["insert"]
        for s in boxes.values():
            if s["header_row"] > p["anchor"]:
                s["header_row"] += delta
                s["avg_row"] += delta
                s["office_avg_row"] += delta
                s["rep_header_row"] += delta
                s["end_row"] += delta
                s["rep_rows"] = {n: (r + delta if r > p["anchor"] else r)
                                 for n, r in s["rep_rows"].items()}
    for p in plans:
        base = p["anchor"] + _shift_above(p["anchor"])
        for i, name in enumerate(p["names"]):
            boxes[p["box"]]["rep_rows"][_norm(name)] = base + 1 + i
    return added


# -------------------------------------------------------------------- write
def write_today(ws, boxes: dict, today: dt.date, parsed: dict, *,
                dry_run: bool = False, logfn=print) -> dict:
    """Write today's B:C pair for every box on this tab.

    B<header> is the DATE written ISO via USER_ENTERED — the cell carries a real
    date number format and a 'Thu 7/30/26' string would sit in it as text.
    Every roster row with no value today is explicitly BLANKED so a re-run can
    never leave yesterday's number under today's date.
    """
    office = parsed.get("office_total", {})
    reps = parsed.get("reps", {})
    by_key = {_norm(n): per_box for n, per_box in reps.items()}
    step = col_step(boxes)
    cells: list = []
    summary: dict = {}

    def _row(*values) -> list:
        """Today's cells for one row: the pair, or just the % when the tab
        carries no units column (writing a count into C would land on the
        PREVIOUS day's percentage there)."""
        return [list(values[:step])]

    for box, sect in boxes.items():
        end = "C" if step == 2 else "B"
        cells += [
            {"range": f"'{ws.title}'!B{sect['header_row']}",
             "values": [[today.isoformat()]]},
            {"range": f"'{ws.title}'!B{sect['rep_header_row']}:"
                      f"{end}{sect['rep_header_row']}",
             "values": _row("%", "units")},
            {"range": f"'{ws.title}'!B{sect['avg_row']}:{end}{sect['avg_row']}",
             "values": _row((office.get(box) or {}).get("pct", ""),
                            (office.get(box) or {}).get("units", ""))},
        ]

        s = {"filled": 0, "blank": [], "unmatched": [],
             "avg": (office.get(box) or {}).get("pct", "")}
        for key, row in sect["rep_rows"].items():
            slot = (by_key.get(key) or {}).get(box) or {}
            pct, units = slot.get("pct", ""), slot.get("units", "")
            if pct:
                s["filled"] += 1
            else:
                s["blank"].append(key.title())
            cells.append({"range": f"'{ws.title}'!B{row}:{end}{row}",
                          "values": _row(pct, units)})
        s["unmatched"] = sorted(n for n, per_box in reps.items()
                                if _norm(n) not in sect["rep_rows"]
                                and (per_box.get(box) or {}).get("pct"))
        s["blank"] = sorted(s["blank"])
        summary[box] = s

    if dry_run:
        for box, s in summary.items():
            logfn(f"  (dry-run) {box}: avg {s['avg'] or '-'}, {s['filled']} "
                  f"owner cell(s), {len(s['blank'])} blank, "
                  f"{len(s['unmatched'])} unmatched")
        return summary

    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": cells})
    return summary


# ------------------------------------------------------------------ styling
def merge_headers(ws, boxes: dict, *, first_col_0: int = 1,
                  dry_run: bool = False) -> None:
    """Span each box's date across its B:C pair. The insert leaves the new pair
    unmerged (the old merge travelled right with the columns it covered).

    No-op on a tab with no units column — there is nothing to span."""
    if dry_run or not boxes or col_step(boxes) != 2:
        return
    ws.spreadsheet.batch_update({"requests": [{
        "mergeCells": {
            "range": {"sheetId": ws.id,
                      "startRowIndex": s["header_row"] - 1,
                      "endRowIndex": s["header_row"],
                      "startColumnIndex": first_col_0,
                      "endColumnIndex": first_col_0 + 2},
            "mergeType": "MERGE_ALL",
        }} for s in boxes.values()]})


def format_pair(ws, boxes: dict, *, first_col_0: int = 1,
                dry_run: bool = False, logfn=print) -> int:
    """Stamp the house style onto ONE day pair (default B:C).

    Called after every insert so a day's columns can never inherit a degraded
    neighbour. `first_col_0` lets --reformat walk the whole history.
    """
    step = col_step(boxes)
    requests: list = []

    def _formats(klass: str) -> tuple:
        pair = STYLE[klass]
        return pair if step == 2 else (_merge_edges(pair),)

    def _paint(row_start_0: int, row_end_0: int, klass: str) -> None:
        for offset, fmt in enumerate(_formats(klass)):
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": row_start_0, "endRowIndex": row_end_0,
                          "startColumnIndex": first_col_0 + offset,
                          "endColumnIndex": first_col_0 + offset + 1},
                "cell": {"userEnteredFormat": fmt},
                "fields": _FORMAT_FIELDS}})

    for sect in boxes.values():
        _paint(sect["header_row"] - 1, sect["header_row"], "header")
        _paint(sect["avg_row"] - 1, sect["avg_row"], "avg")
        _paint(sect["rep_header_row"] - 1, sect["rep_header_row"], "rep_header")
        if sect["rep_rows"]:
            last = max(sect["rep_rows"].values())
            _paint(sect["rep_header_row"], last, "rep")

    if dry_run:
        logfn(f"  (dry-run) would stamp {len(requests)} formatting block(s) "
              f"onto the day pair")
        return len(requests)
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})
    return len(requests)


def day_columns(ws, boxes: dict) -> list:
    """0-indexed first column of every day that carries a date header — B, D,
    F ... on a paired tab, B, C, D ... on a single-column one. Used by
    --reformat."""
    if not boxes:
        return []
    row = min(s["header_row"] for s in boxes.values())
    values = _retry(ws.row_values, row)
    out = []
    for c0 in range(1, ws.col_count, col_step(boxes)):
        val = values[c0] if c0 < len(values) else ""
        if not (val or "").strip():
            break
        out.append(c0)
    return out
