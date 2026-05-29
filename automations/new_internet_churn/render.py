"""Render the 4 churn-period sections as multi-week PNGs for the daily
Slack post in the Metrics thread.

Megan 2026-05-28: the Slack image should match the look of Eve's
manual screenshots — multiple trailing week columns per rep, not just
today's snapshot. We read the leftmost N date-col-pairs from the sheet
(after write_today fills today's B+C) and render a wide PNG showing
rep + that history.

One PNG per period (0-30 / 30 / 60 / 90). Each PNG shows:
  - Orange title bar (NEW INTERNET CHURN — <period> DAY)
  - Office Avg row across N weeks
  - Repeating "% / units" col headers per week
  - Rep rows: only those with non-blank today, sorted by today's %
    desc; each row shows the rep's % + units for each of N weeks
  - Conditional %-cell coloring (red/yellow/green per period threshold)
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

# How many trailing week-cols to show in each image. Eve's manual posts
# typically show ~7-8 days; matches the "last seven days" rule of thumb.
N_WEEKS = 7

# Layout constants
PAD = 12
ROW_H = 24
TITLE_H = 56
HEADER_BAR_H = 28
NAME_COL_W = 180
WEEK_COL_W = 100   # split into 60 (pct) + 40 (units) per week-pair
PCT_SUB_W  = 60
UNIT_SUB_W = 40

# Palette — orange (New Internet)
TITLE_BG       = (234, 144, 60)
TITLE_FG       = (255, 255, 255)
OFFICE_AVG_BG  = (250, 222, 187)
COL_HEADER_BG  = (0, 0, 0)
COL_HEADER_FG  = (255, 255, 255)
ROW_BG         = (245, 247, 252)
GREEN          = (147, 196, 125)
YELLOW         = (255, 217, 102)
RED            = (224, 102, 102)
TEXT           = (40, 40, 40)
SECTION_HDR_BG = (250, 178, 117)  # the orange band on date header

# Per-period thresholds (from Eve's transcript)
THRESHOLDS = {
    "0-30": (2.0, 3.5),
    "30":   (5.0, 8.0),
    "60":   (5.0, 8.0),
    "90":   (5.0, 8.0),
}

TITLE_BY_PERIOD = {
    "0-30": "NEW INTERNET CHURN — 0-30 DAY",
    "30":   "NEW INTERNET CHURN — 30 DAY",
    "60":   "NEW INTERNET CHURN — 60 DAY",
    "90":   "NEW INTERNET CHURN — 90 DAY",
}


def _font(size: int, bold: bool = False):
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    try:
        return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)
    except Exception:
        return ImageFont.load_default()


def _color_for(period: str, pct_str: str) -> Tuple[int, int, int]:
    pct = (pct_str or "").strip().rstrip("%")
    if not pct:
        return (255, 255, 255)   # blank → white
    try:
        v = float(pct)
    except ValueError:
        return (255, 255, 255)
    g_max, r_min = THRESHOLDS.get(period, (2.0, 3.5))
    if v <= g_max:
        return GREEN
    if v >= r_min:
        return RED
    return YELLOW


def _col_letter(idx_0: int) -> str:
    n = idx_0
    out = ""
    while True:
        n, rem = divmod(n, 26)
        out = chr(ord("A") + rem) + out
        if n == 0:
            return out
        n -= 1


def _read_section(ws, section: dict, n_weeks: int) -> dict:
    """Read the rep block + headers + office avg for the given section,
    spanning A through the last week-pair we care about."""
    end_col_0 = 1 + n_weeks * 2
    end_col = _col_letter(end_col_0 - 1)
    header_row = section["header_row"]
    avg_row = section["office_avg_row"]
    rep_hdr_row = section["rep_header_row"]
    rep_rows = section["rep_rows"]
    last_rep_row = max(rep_rows.values()) if rep_rows else rep_hdr_row

    ranges = [
        f"A{header_row}:{end_col}{header_row}",
        f"A{avg_row}:{end_col}{avg_row}",
        f"A{rep_hdr_row}:{end_col}{rep_hdr_row}",
        f"A{rep_hdr_row + 1}:{end_col}{last_rep_row}",
    ]
    result = ws.batch_get(ranges)

    def row_or_empty(r):
        return r[0] if r else []

    date_labels_row = row_or_empty(result[0])
    office_avg_row  = row_or_empty(result[1])
    rep_header_row  = row_or_empty(result[2])
    rep_rows_data   = result[3] if result[3] else []

    # Date labels live at B (idx 1) since headers are merged B+C — D, F,
    # H, ... are the next dates.
    dates = []
    for i in range(1, min(len(date_labels_row), end_col_0), 2):
        d = (date_labels_row[i] if i < len(date_labels_row) else "").strip()
        dates.append(d)
    # Pad to n_weeks
    while len(dates) < n_weeks:
        dates.append("")

    # Office Avg values for each week-pair
    avg_pairs = []
    for i in range(1, end_col_0, 2):
        pct = (office_avg_row[i] if i < len(office_avg_row) else "").strip()
        units = (office_avg_row[i + 1] if i + 1 < len(office_avg_row) else "").strip()
        avg_pairs.append((pct, units))

    # Rep rows: each has rep_name at idx 0, then alternating (pct, units)
    reps = []
    for rep_row in rep_rows_data:
        if not rep_row:
            continue
        name = (rep_row[0] if rep_row else "").strip()
        if not name:
            continue
        pairs = []
        for i in range(1, end_col_0, 2):
            pct = (rep_row[i] if i < len(rep_row) else "").strip()
            units = (rep_row[i + 1] if i + 1 < len(rep_row) else "").strip()
            pairs.append((pct, units))
        # Skip reps with no value in ANY of the N weeks (hidden rows).
        if not any(pct for pct, _ in pairs):
            continue
        reps.append((name, pairs))

    # Sort reps by today's pct descending (today = first week pair).
    def _sort_key(item):
        _, pairs = item
        pct_today = (pairs[0][0] if pairs else "").strip().rstrip("%")
        if not pct_today:
            return (1, 0.0)
        try:
            return (0, -float(pct_today))
        except ValueError:
            return (1, 0.0)

    reps.sort(key=_sort_key)

    return {
        "dates": dates,
        "office_avg": avg_pairs,
        "reps": reps,
    }


def render_multi_week(
    ws,
    section: dict,
    period: str,
    today: dt.date,
    out_path: Path,
    n_weeks: int = N_WEEKS,
    title_bg=TITLE_BG,
    office_avg_bg=OFFICE_AVG_BG,
    title_text=None,
) -> Path:
    """Render one section as a multi-week PNG. `section` is one of the
    dicts find_sections() returns. `period` is '0-30' / '30' / etc."""
    data = _read_section(ws, section, n_weeks)
    dates = data["dates"]
    office_avg = data["office_avg"]
    reps = data["reps"]

    total_w = NAME_COL_W + WEEK_COL_W * n_weeks + PAD * 2
    h = (TITLE_H + ROW_H * 2 + HEADER_BAR_H        # title + section-hdr + avg + col-hdr
         + ROW_H * max(len(reps), 1) + PAD * 2)

    img = Image.new("RGB", (total_w, h), "white")
    d = ImageDraw.Draw(img)
    f10 = _font(10)
    f11 = _font(11)
    f11b = _font(11, bold=True)
    f14b = _font(14, bold=True)
    f16b = _font(16, bold=True)

    x = PAD
    y = PAD

    # 1. Title bar
    d.rectangle([x, y, x + total_w - PAD * 2, y + TITLE_H], fill=title_bg)
    title = title_text or TITLE_BY_PERIOD.get(period, f"CHURN — {period} DAY")
    d.text((x + 12, y + 6), title, fill=TITLE_FG, font=f16b)
    sub = f"Last {n_weeks} fills (most recent first) · " \
          f"{today.strftime('%a')} {today.month}/{today.day}/{today.year % 100}"
    d.text((x + 12, y + 30), sub, fill=TITLE_FG, font=f11b)
    y += TITLE_H

    # 2. Section-header row (date labels per week-pair)
    d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=SECTION_HDR_BG)
    d.text((x + 8, y + 4), "Date", fill=TEXT, font=f11b)
    cx = x + NAME_COL_W
    for i in range(n_weeks):
        date_str = dates[i] if i < len(dates) else ""
        # short date: strip 'Thu ' prefix and year
        short = re.sub(r"^\w+ ", "", date_str)
        short = re.sub(r"/\d+$", "", short)
        d.text((cx + 6, y + 4), short, fill=TEXT, font=f11b)
        cx += WEEK_COL_W
    y += ROW_H

    # 3. Office Avg row
    d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=office_avg_bg)
    d.text((x + 8, y + 4), "Office Avg", fill=TEXT, font=f11b)
    cx = x + NAME_COL_W
    for i in range(n_weeks):
        pct, units = (office_avg[i] if i < len(office_avg) else ("", ""))
        # color the pct sub-cell based on threshold
        color = _color_for(period, pct)
        d.rectangle([cx, y, cx + PCT_SUB_W, y + ROW_H], fill=color)
        d.text((cx + 4, y + 4), pct or "", fill=TEXT, font=f11b)
        d.text((cx + PCT_SUB_W + 4, y + 4), units or "", fill=TEXT, font=f11)
        cx += WEEK_COL_W
    y += ROW_H

    # 4. Col-header bar (Rep / % units repeating)
    d.rectangle([x, y, x + total_w - PAD * 2, y + HEADER_BAR_H], fill=COL_HEADER_BG)
    d.text((x + 8, y + 6), "Rep", fill=COL_HEADER_FG, font=f14b)
    cx = x + NAME_COL_W
    for i in range(n_weeks):
        d.text((cx + 4, y + 8), "%", fill=COL_HEADER_FG, font=f11b)
        d.text((cx + PCT_SUB_W + 4, y + 8), "units", fill=COL_HEADER_FG, font=f11b)
        cx += WEEK_COL_W
    y += HEADER_BAR_H

    if not reps:
        d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=ROW_BG)
        d.text((x + 12, y + 4), "(no reps with data this period)",
               fill=(140, 140, 140), font=f11)
        img.save(out_path)
        return out_path

    # 5. Rep rows
    for ri, (name, pairs) in enumerate(reps):
        bg = "white" if ri % 2 == 0 else ROW_BG
        d.rectangle([x, y, x + NAME_COL_W, y + ROW_H], fill=bg)
        d.text((x + 8, y + 4), name[:24], fill=TEXT, font=f11)
        cx = x + NAME_COL_W
        for i in range(n_weeks):
            pct, units = (pairs[i] if i < len(pairs) else ("", ""))
            color = _color_for(period, pct)
            d.rectangle([cx, y, cx + PCT_SUB_W, y + ROW_H], fill=color)
            d.rectangle([cx + PCT_SUB_W, y, cx + WEEK_COL_W, y + ROW_H], fill=bg)
            if pct:
                d.text((cx + 4, y + 4), pct, fill=TEXT, font=f11b)
            if units:
                d.text((cx + PCT_SUB_W + 4, y + 4), units, fill=TEXT, font=f11)
            cx += WEEK_COL_W
        y += ROW_H

    img.save(out_path)
    return out_path


def render_all_sections(ws, sections: dict, today: dt.date,
                         out_dir: Path,
                         n_weeks: int = N_WEEKS) -> dict:
    """Render all 4 period sections into PNGs."""
    out: dict = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for period, sect in sections.items():
        path = out_dir / f"new_internet_churn_{period.replace('-', '_')}_day.png"
        render_multi_week(ws, sect, period, today, path, n_weeks=n_weeks)
        out[period] = path
    return out
