"""Render a ONE-COLUMN-PER-DAY metrics box to a PNG for the drafts email.

The churn engine (new_internet_churn.render) can't draw these: it reads each
day as a B+C PAIR (% + units) and would take yesterday's percentage as today's
unit count. The cancel-rate / activation-rate / ABP / 6-days-out tabs carry a
SINGLE column per day, so they get their own reader and their own draw pass.

Everything else is deliberately borrowed from that engine — same fonts, same
title bar, same orange date band, same alternating rep rows — so a new section
reads as a sibling of the churn images sitting above it in the same email, not
as a different report.

TWO DELIBERATE DIFFERENCES from the churn render:

  * Cell colors are READ OFF THE TAB, not hardcoded. The churn engine carries
    its thresholds in Python; these boxes take whatever conditional-format
    bands Eve has set on the sheet, so the email can never disagree with the
    sheet, and re-banding a tab needs no code change. Google does not return
    conditional formatting as a cell color (effectiveFormat ignores it), so the
    RULES are fetched and evaluated here against each value. A tab with no
    rules renders plain, exactly as before.
  * Every roster row is drawn, including a rep who is blank or 0% today. The
    churn image hides those on purpose (Raf wants Slack to show only ACTIVE
    churn), but on these boxes 0% is the story — a 0% activation rate is the
    number the captain most needs to see, and a blank means Tableau had nothing
    for that rep, which is also worth seeing.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from automations.new_internet_churn.render import (
    _font, _col_letter, contrast_fg,
    PAD, ROW_H, HEADER_BAR_H, NAME_COL_W,
    TITLE_BG, TITLE_FG, TEXT, ROW_BG, OFFICE_AVG_BG,
    COL_HEADER_BG, COL_HEADER_FG, SECTION_HDR_BG,
)

# One day per column (the churn image spends 120px on a %+units pair).
DAY_COL_W = 78
N_DAYS = 7
TITLE_H = 36
AVG_LABEL = "Captainship Avg"


# ------------------------------------------------------- conditional formats
# One metadata fetch per SPREADSHEET, reused for every box on it (a fiber
# captain has two boxes per workbook, and five captains share each workbook).
_CF_CACHE: dict = {}


def _cf_rules(ws) -> list:
    """The tab's conditional-format rules, in the order Sheets evaluates them
    (first match wins). Empty on any failure — a missing color must never cost
    us the image."""
    sid = ws.spreadsheet.id
    if sid not in _CF_CACHE:
        try:
            meta = ws.spreadsheet.fetch_sheet_metadata(
                {"fields": "sheets(properties(sheetId),conditionalFormats)"})
            _CF_CACHE[sid] = {
                s["properties"]["sheetId"]: (s.get("conditionalFormats") or [])
                for s in meta["sheets"]}
        except Exception:  # noqa: BLE001
            _CF_CACHE[sid] = {}
    return _CF_CACHE[sid].get(ws.id, [])


def _num(raw: str):
    """'96.70%' -> 0.967, '85%' -> 0.85, '0.85' -> 0.85. None if not a number.
    Cell values arrive formatted and rule thresholds are typed as percentages,
    so both sides go through the same parse."""
    s = (raw or "").strip()
    if not s:
        return None
    pct = s.endswith("%")
    try:
        v = float(s.rstrip("%").replace(",", ""))
    except ValueError:
        return None
    return v / 100 if pct else v


def _matches(cond: dict, value: float) -> bool:
    vals = [_num(v.get("userEnteredValue", ""))
            for v in cond.get("values", [])]
    if any(v is None for v in vals):
        return False
    t = cond.get("type")
    if t == "NUMBER_GREATER":        return value > vals[0]
    if t == "NUMBER_GREATER_THAN_EQ": return value >= vals[0]
    if t == "NUMBER_LESS":           return value < vals[0]
    if t == "NUMBER_LESS_THAN_EQ":   return value <= vals[0]
    if t == "NUMBER_EQ":             return value == vals[0]
    if t == "NUMBER_NOT_EQ":         return value != vals[0]
    if t == "NUMBER_BETWEEN":        return vals[0] <= value <= vals[1]
    if t == "NUMBER_NOT_BETWEEN":    return not (vals[0] <= value <= vals[1])
    return False        # anything else (text/date/gradient) isn't a band


def _in_range(rng: dict, row: int, col0: int) -> bool:
    """`row` is 1-indexed, `col0` 0-indexed — the shapes each side already
    speaks. Absent bounds mean unbounded, per the Sheets API."""
    r0 = rng.get("startRowIndex", 0)
    r1 = rng.get("endRowIndex")
    c0 = rng.get("startColumnIndex", 0)
    c1 = rng.get("endColumnIndex")
    if row - 1 < r0 or (r1 is not None and row - 1 >= r1):
        return False
    return not (col0 < c0 or (c1 is not None and col0 >= c1))


def _cf_color(rules: list, row: int, col0: int, raw: str):
    """The background Sheets would paint on this cell, or None.

    FIRST match wins, which is how Sheets itself resolves overlapping rules —
    on these tabs '<= 30% green' deliberately sits above '30-84.99% yellow' so
    exactly 30% reads green."""
    value = _num(raw)
    if value is None or not rules:
        return None
    for rule in rules:
        brule = rule.get("booleanRule")
        if not brule:
            continue        # gradient rules aren't bands; skip rather than guess
        if not any(_in_range(r, row, col0) for r in rule.get("ranges", [])):
            continue
        if not _matches(brule.get("condition", {}), value):
            continue
        c = (brule.get("format") or {}).get("backgroundColor")
        if not c:
            return None
        return tuple(int(round(c.get(k, 0) * 255))
                     for k in ("red", "green", "blue"))
    return None


def _read_box(ws, section: dict, n_days: int) -> dict:
    """Read one box: date headers, the Captainship Avg row and every rep row,
    across A..<n_days columns>.

    Returns {"dates": [...], "avg": [...], "avg_row": int,
             "reps": [(name, sheet_row, [v, ...]), ...]} with every value list
    padded to n_days. The sheet row rides along because the conditional-format
    rules are addressed by row.
    """
    end_col_0 = 1 + n_days
    end_col = _col_letter(end_col_0 - 1)
    header_row = section["header_row"]
    # The three fill modules name this row differently — 'office_avg_row' in
    # the churn-shaped dicts (activation, ABP/6-days) and 'avg_row' in
    # captainship_cancel_rate. Same row, same meaning; accept both rather than
    # rename a key another report writes to.
    avg_row = section.get("office_avg_row") or section["avg_row"]
    rep_hdr_row = section["rep_header_row"]
    rep_rows = section["rep_rows"]
    last_rep_row = max(rep_rows.values()) if rep_rows else rep_hdr_row

    result = ws.batch_get([
        f"A{header_row}:{end_col}{header_row}",
        f"A{avg_row}:{end_col}{avg_row}",
        f"A{rep_hdr_row + 1}:{end_col}{last_rep_row}",
    ])

    def row_or_empty(r):
        return r[0] if r else []

    def cells(row):
        return [(row[i] if i < len(row) else "").strip()
                for i in range(1, end_col_0)]

    dates = cells(row_or_empty(result[0]))
    avg = cells(row_or_empty(result[1]))

    reps = []
    for i, row in enumerate(result[2] if result[2] else []):
        name = (row[0] if row else "").strip()
        if not name:
            continue
        # The read starts at rep_hdr_row + 1 and is contiguous, so the offset
        # IS the sheet row. Captured before the sort below reorders them.
        reps.append((name, rep_hdr_row + 1 + i, cells(row)))

    # Best first by TODAY's number (column B), blanks last. Deliberately not
    # the sheet's own row order: these tabs list reps in whatever order they
    # were added, which is meaningless to a reader.
    def _key(item):
        v = _num(item[2][0] if item[2] else "")
        return (1, 0.0) if v is None else (0, -v)

    reps.sort(key=_key)
    return {"dates": dates, "avg": avg, "avg_row": avg_row, "reps": reps}


def visible_days(dates: list) -> int:
    """How many day columns actually carry a date header.

    These tabs are days old, not months — the cancel/activation boxes opened
    2026-07-28 and ABP on 07-29 — so a fixed 7-column grid would draw five
    empty columns and read as missing data rather than as a young report.
    """
    n = 0
    for d in dates:
        if not d:
            break
        n += 1
    return n


def render_box(
    ws,
    section: dict,
    title: str,
    out_path: Path,
    *,
    today: Optional[dt.date] = None,   # accepted for signature parity; the
                                       # dates drawn are the sheet's own
    n_days: int = N_DAYS,
    title_bg=TITLE_BG,
    title_fg=None,
    value_header: str = "%",
) -> Path:
    """Draw one metrics box as a PNG. `section` is a dict shaped like the ones
    find_boxes()/find_sections() return (header_row, office_avg_row,
    rep_header_row, rep_rows)."""
    data = _read_box(ws, section, n_days)
    shown = max(visible_days(data["dates"]), 1)
    dates, avg, reps = data["dates"], data["avg"], data["reps"]
    rules = _cf_rules(ws)

    f11 = _font(11)
    f11b = _font(11, bold=True)
    f14b = _font(14, bold=True)
    f16b = _font(16, bold=True)

    # Width is driven by the day columns, but a young box has ONE column and
    # would come out narrower than its own title — 'ONGOING 6+ DAYS SALES RATE'
    # was cut off mid-word on the first render. Floor the width at the title.
    title_w = int(f16b.getlength(title)) + 24 + PAD * 2
    total_w = max(NAME_COL_W + DAY_COL_W * shown + PAD * 2, title_w)
    # Stretch the day columns over whatever width the title forced, so the
    # grid stays flush right instead of leaving a blank strip.
    day_w = (total_w - PAD * 2 - NAME_COL_W) / shown
    h = (TITLE_H + ROW_H * 2 + HEADER_BAR_H
         + ROW_H * max(len(reps), 1) + PAD * 2)

    img = Image.new("RGB", (total_w, h), "white")
    d = ImageDraw.Draw(img)

    x = y = PAD
    inner_w = total_w - PAD * 2

    # 1. Title bar (captain's brand color, auto-contrasted text)
    d.rectangle([x, y, x + inner_w, y + TITLE_H], fill=title_bg)
    d.text((x + 12, y + (TITLE_H - 18) // 2), title,
           fill=title_fg or contrast_fg(title_bg), font=f16b)
    y += TITLE_H

    # 2. Date band
    d.rectangle([x, y, x + inner_w, y + ROW_H], fill=SECTION_HDR_BG)
    d.text((x + 8, y + 4), "Date", fill=TEXT, font=f11b)
    cx = x + NAME_COL_W
    for i in range(shown):
        # 'Wed 7/29/26' -> '7/29', same shortening the churn band uses
        short = re.sub(r"/\d+$", "", re.sub(r"^\w+ ", "", dates[i] if i < len(dates) else ""))
        tw = d.textlength(short, font=f11b)
        d.text((cx + (day_w - tw) / 2, y + 4), short, fill=TEXT, font=f11b)
        cx += day_w
    y += ROW_H

    # 3. Captainship Avg row — banded per cell like the sheet's own avg row
    d.rectangle([x, y, x + inner_w, y + ROW_H], fill=OFFICE_AVG_BG)
    d.text((x + 8, y + 4), AVG_LABEL, fill=TEXT, font=f11b)
    cx = x + NAME_COL_W
    for i in range(shown):
        v = avg[i] if i < len(avg) else ""
        color = _cf_color(rules, data["avg_row"], 1 + i, v)
        if color:
            d.rectangle([cx, y, cx + day_w, y + ROW_H], fill=color)
        tw = d.textlength(v, font=f11b)
        d.text((cx + (day_w - tw) / 2, y + 4), v, fill=TEXT, font=f11b)
        cx += day_w
    y += ROW_H

    # 4. Column header
    d.rectangle([x, y, x + inner_w, y + HEADER_BAR_H], fill=COL_HEADER_BG)
    d.text((x + 8, y + 6), "Rep", fill=COL_HEADER_FG, font=f14b)
    cx = x + NAME_COL_W
    for i in range(shown):
        tw = d.textlength(value_header, font=f11b)
        d.text((cx + (day_w - tw) / 2, y + 8), value_header,
               fill=COL_HEADER_FG, font=f11b)
        cx += day_w
    y += HEADER_BAR_H

    if not reps:
        d.rectangle([x, y, x + inner_w, y + ROW_H], fill=ROW_BG)
        d.text((x + 12, y + 4), "(no reps on this tab yet)",
               fill=(140, 140, 140), font=f11)
        img.save(out_path)
        return out_path

    # 5. Rep rows
    for ri, (name, sheet_row, values) in enumerate(reps):
        bg = "white" if ri % 2 == 0 else ROW_BG
        d.rectangle([x, y, x + inner_w, y + ROW_H], fill=bg)
        d.text((x + 8, y + 4), name[:24], fill=TEXT, font=f11)
        cx = x + NAME_COL_W
        for i in range(shown):
            v = values[i] if i < len(values) else ""
            color = _cf_color(rules, sheet_row, 1 + i, v)
            if color:
                d.rectangle([cx, y, cx + day_w, y + ROW_H], fill=color)
            tw = d.textlength(v, font=f11b)
            d.text((cx + (day_w - tw) / 2, y + 4), v, fill=TEXT, font=f11b)
            cx += day_w
        y += ROW_H

    img.save(out_path)
    return out_path
