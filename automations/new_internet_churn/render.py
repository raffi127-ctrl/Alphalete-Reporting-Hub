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
WEEK_COL_W = 120   # split into 60 (pct) + 60 (units) per week-pair
PCT_SUB_W  = 60
UNIT_SUB_W = 60    # widened so units like '69/2,768' aren't clipped
                   # (esp. the last column, which hit the image edge)

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
    "120":  (5.0, 8.0),   # B2B 5th bucket — same band as 30/60/90
}

TITLE_BY_PERIOD = {
    "0-30": "NEW INTERNET CHURN — 0-30 DAY",
    "30":   "NEW INTERNET CHURN — 30 DAY",
    "60":   "NEW INTERNET CHURN — 60 DAY",
    "90":   "NEW INTERNET CHURN — 90 DAY",
    "120":  "NEW INTERNET CHURN — 120 DAY",
}


# Font candidates in preference order — first that loads wins. Mirrors
# scheduled_6_days_out/render.py so the churn PNGs render with real Arial
# on BOTH Windows (Eve's Hub) and macOS, not the bitmap fallback. The old
# Mac-only path fell back to load_default() on Windows (tiny, illegible).
_FONT_REG = ["arial.ttf", "Arial.ttf",
             "/System/Library/Fonts/Supplemental/Arial.ttf",
             "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
_FONT_BOLD = ["arialbd.ttf", "Arial Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"]


def _font(size: int, bold: bool = False):
    for name in (_FONT_BOLD if bold else _FONT_REG):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def contrast_fg(bg) -> Tuple[int, int, int]:
    """Pick black or white text for best legibility on `bg` (a '#rrggbb'
    string or an (r,g,b) tuple). Used so pale brand title bars (e.g. Luis
    '#B4B3F8') get dark text instead of unreadable white."""
    if isinstance(bg, str):
        c = bg.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    else:
        r, g, b = bg[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if luminance > 150 else (255, 255, 255)


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
        # Skip reps whose TODAY % (col B = first week-pair) is blank
        # OR exactly 0.00% — Raf 2026-05-29: prefers smaller Slack
        # screenshots showing only reps with ACTIVE churn (>0% today).
        # The sheet still carries every 0% row; this filter is just
        # for the Slack image.
        today_pct_str = (pairs[0][0] if pairs else "").strip().rstrip("%")
        if not today_pct_str:
            continue
        try:
            if float(today_pct_str) <= 0:
                continue
        except ValueError:
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
    show_subtitle: bool = True,
    title_fg=None,
) -> Path:
    """Render one section as a multi-week PNG. `section` is one of the
    dicts find_sections() returns. `period` is '0-30' / '30' / etc."""
    data = _read_section(ws, section, n_weeks)
    dates = data["dates"]
    office_avg = data["office_avg"]
    reps = data["reps"]

    total_w = NAME_COL_W + WEEK_COL_W * n_weeks + PAD * 2
    # Shorter title bar when the subtitle is suppressed (captainship email
    # drafts drop it; the Slack post keeps it).
    title_h = TITLE_H if show_subtitle else 36
    h = (title_h + ROW_H * 2 + HEADER_BAR_H        # title + section-hdr + avg + col-hdr
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
    d.rectangle([x, y, x + total_w - PAD * 2, y + title_h], fill=title_bg)
    title = title_text or TITLE_BY_PERIOD.get(period, f"CHURN — {period} DAY")
    title_y = y + 6 if show_subtitle else y + (title_h - 18) // 2
    # title_fg defaults to white (Slack post unchanged); captainship drafts
    # pass an auto-contrast color so pale brand bars get dark text.
    d.text((x + 12, title_y), title, fill=title_fg or TITLE_FG, font=f16b)
    if show_subtitle:
        sub = f"Last {n_weeks} fills (most recent first) · " \
              f"{today.strftime('%a')} {today.month}/{today.day}/{today.year % 100}"
        d.text((x + 12, y + 30), sub, fill=TITLE_FG, font=f11b)
    y += title_h

    # 2. Section-header row (date labels per week-pair)
    d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=SECTION_HDR_BG)
    d.text((x + 8, y + 4), "Date", fill=TEXT, font=f11b)
    cx = x + NAME_COL_W
    for i in range(n_weeks):
        date_str = dates[i] if i < len(dates) else ""
        # short date: strip 'Thu ' prefix and year
        short = re.sub(r"^\w+ ", "", date_str)
        short = re.sub(r"/\d+$", "", short)
        # Center the date over its full week-pair (% + units columns).
        tw = d.textlength(short, font=f11b)
        d.text((cx + (WEEK_COL_W - tw) / 2, y + 4), short, fill=TEXT, font=f11b)
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


def section_has_data(ws, section: dict, n_weeks: int = N_WEEKS) -> bool:
    """True if the section has ANY churn data on the sheet — either a
    non-blank Office Avg value OR at least one rep with a non-blank value
    across the N week-pairs. Rows are taken from find_sections (label-
    anchored), never hardcoded indices.

    Skip-empty rendering (Megan 2026-06-28): a YOUNG office (e.g. Rashad
    Reed) only has 0-30 Day data filled — the 30/60/90 section headers
    exist on the tab but carry no avg/rep numbers yet. We omit those empty
    sections from the Slack post instead of rendering blank images.

    Raf's office has all 4 sections populated, so this returns True for
    every section → all 4 still render, byte-for-byte as before. The only
    behavior change is for sections that are entirely blank.
    """
    end_col_0 = 1 + n_weeks * 2
    end_col = _col_letter(end_col_0 - 1)
    avg_row = section["office_avg_row"]
    rep_hdr_row = section["rep_header_row"]
    rep_rows = section["rep_rows"]
    last_rep_row = max(rep_rows.values()) if rep_rows else rep_hdr_row

    ranges = [
        f"A{avg_row}:{end_col}{avg_row}",
        f"A{rep_hdr_row + 1}:{end_col}{last_rep_row}",
    ]
    result = ws.batch_get(ranges)

    def _nonblank_in_pairs(row) -> bool:
        # Scan the (pct, units) value columns (B onward = idx 1+); a single
        # non-blank cell means the section has data.
        for i in range(1, min(len(row), end_col_0)):
            if (row[i] or "").strip():
                return True
        return False

    avg_row_vals = result[0][0] if result[0] else []
    if _nonblank_in_pairs(avg_row_vals):
        return True

    rep_rows_data = result[1] if result[1] else []
    for rep_row in rep_rows_data:
        if rep_row and _nonblank_in_pairs(rep_row):
            return True
    return False


def render_all_sections(ws, sections: dict, today: dt.date,
                         out_dir: Path,
                         n_weeks: int = N_WEEKS) -> dict:
    """Render every period section that HAS data into a PNG.

    Empty sections (no Office Avg + no rep values) are skipped so a young
    office only posts the section(s) it actually has. Fully-populated
    offices (Raf) render all 4 exactly as before."""
    out: dict = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for period, sect in sections.items():
        if not section_has_data(ws, sect, n_weeks):
            continue
        path = out_dir / f"new_internet_churn_{period.replace('-', '_')}_day.png"
        render_multi_week(ws, sect, period, today, path, n_weeks=n_weeks)
        out[period] = path
    return out
