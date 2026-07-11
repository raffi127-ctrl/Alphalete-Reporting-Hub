"""Render the New Internet ABP% tab as a multi-week PNG for the daily
Slack post, mirroring the churn image's look (title bar, Office Avg row,
repeating week-pair columns of % / units, rep rows sorted by today's %).

Single section, so much simpler than churn/render.py. Reuses churn's
font + layout constants for a visually consistent post. Cells are drawn
neutral — ABP color thresholds haven't been specified by Raf, so we
don't assert red/yellow/green pass-fail bands here (unlike churn, where
Eve gave explicit thresholds). Higher ABP% = better; only the top data
reps are shown (today's % non-blank).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw

from automations.new_internet_abp import fill as abp_fill
from automations.new_internet_churn.render import (
    _font, PAD, ROW_H, TITLE_H, HEADER_BAR_H, NAME_COL_W, WEEK_COL_W,
    PCT_SUB_W, UNIT_SUB_W, TITLE_FG, COL_HEADER_BG, COL_HEADER_FG,
    ROW_BG, TEXT, GREEN, YELLOW, RED,
)
from automations.new_internet_abp.bands import band_color_rgb

N_WEEKS = 7
# Blue title bar so it's visually distinct from churn's orange in the
# thread (💳 New Internet ABP %).
TITLE_BG = (60, 120, 216)
OFFICE_AVG_BG = (200, 220, 250)
SECTION_HDR_BG = (120, 165, 232)
TITLE = "NEW INTERNET ABP %"
SUBTITLE = "Raf's Local Office"


def _read_tab(ws, n_weeks: int) -> dict:
    """Read header dates, office avg, and rep rows for the first n_weeks
    date-pairs (cols B.. ). Layout rows are fixed (1/2/3, reps 4+)."""
    end_col_0 = 1 + n_weeks * 2
    end_col = abp_fill._col_index_to_letter(end_col_0 - 1)
    from automations.recruiting_report.fill import _retry
    grid = _retry(ws.get_all_values)

    def row(i0):
        return grid[i0] if i0 < len(grid) else []

    hdr = row(abp_fill.HEADER_ROW - 1)
    avg = row(abp_fill.OFFICE_ROW - 1)

    dates = []
    for i in range(1, end_col_0, 2):
        dates.append((hdr[i] if i < len(hdr) else "").strip())

    def pairs_from(r):
        out = []
        for i in range(1, end_col_0, 2):
            pct = (r[i] if i < len(r) else "").strip()
            units = (r[i + 1] if i + 1 < len(r) else "").strip()
            out.append((pct, units))
        return out

    office_avg = pairs_from(avg)

    reps = []
    for i0 in range(abp_fill.FIRST_REP_ROW - 1, len(grid)):
        r = grid[i0]
        name = (r[0] if r else "").strip()
        if not name:
            continue
        pairs = pairs_from(r)
        today = (pairs[0][0] if pairs else "").strip().rstrip("%")
        if not today:  # only show reps with data today (0% IS shown)
            continue
        reps.append((name, pairs))

    def _key(item):
        _, pairs = item
        t = (pairs[0][0] if pairs else "").strip().rstrip("%")
        try:
            return (0, -float(t))
        except ValueError:
            return (1, 0.0)
    reps.sort(key=_key)
    return {"dates": dates, "office_avg": office_avg, "reps": reps}


def _data_from_parsed(parsed: dict, today: dt.date) -> dict:
    """Build a single-week render `data` dict straight from a parsed pull —
    lets us preview the image WITHOUT writing to the sheet (sandbox-first)."""
    from automations.new_internet_abp import pull
    office = parsed.get("office_total", {})
    reps_in = parsed.get("reps", {})
    date_label = abp_fill._date_label(today)
    reps = []
    for name, slot in reps_in.items():
        if not pull.has_pct(slot):
            continue
        reps.append((name, [(slot.get("pct", ""), pull.fmt_units(slot))]))

    def _key(item):
        _, pairs = item
        t = (pairs[0][0] if pairs else "").strip().rstrip("%")
        try:
            return (0, -float(t))
        except ValueError:
            return (1, 0.0)
    reps.sort(key=_key)
    return {"dates": [date_label],
            "office_avg": [(office.get("pct", ""), pull.fmt_units(office))],
            "reps": reps}


def render_preview(parsed: dict, today: dt.date, out_path: Path,
                   subtitle: str = SUBTITLE) -> Path:
    """Render the image from a parsed pull (single week), no Sheet needed."""
    return _draw(_data_from_parsed(parsed, today), today, out_path,
                 n_weeks=1, subtitle=subtitle)


def render(ws, today: dt.date, out_path: Path, n_weeks: int = N_WEEKS,
           subtitle: str = SUBTITLE) -> Path:
    return _draw(_read_tab(ws, n_weeks), today, out_path, n_weeks=n_weeks,
                 subtitle=subtitle)


def _draw(data: dict, today: dt.date, out_path: Path, n_weeks: int = N_WEEKS,
          subtitle: str = SUBTITLE) -> Path:
    dates, office_avg, reps = data["dates"], data["office_avg"], data["reps"]

    total_w = NAME_COL_W + WEEK_COL_W * n_weeks + PAD * 2
    h = (TITLE_H + ROW_H * 2 + HEADER_BAR_H + ROW_H * max(len(reps), 1) + PAD * 2)
    img = Image.new("RGB", (total_w, h), "white")
    d = ImageDraw.Draw(img)
    f10, f11, f11b, f14b, f16b = (_font(10), _font(11), _font(11, True),
                                  _font(14, True), _font(16, True))
    x, y = PAD, PAD

    # Title bar
    d.rectangle([x, y, x + total_w - PAD * 2, y + TITLE_H], fill=TITLE_BG)
    d.text((x + 10, y + 6), TITLE, font=f16b, fill=TITLE_FG)
    d.text((x + 10, y + 32), f"{subtitle} — {today:%m/%d/%Y}", font=f11, fill=TITLE_FG)
    y += TITLE_H

    name_x = x
    def week_x(w):
        return x + NAME_COL_W + w * WEEK_COL_W

    # Section header row: date labels spanning each week-pair
    d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=SECTION_HDR_BG)
    d.text((name_x + 6, y + 5), "Week ending", font=f11b, fill=TEXT)
    for w, dl in enumerate(dates):
        if dl:
            d.text((week_x(w) + 6, y + 5), dl, font=f11b, fill=TEXT)
    y += ROW_H

    # Office Avg row
    d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=OFFICE_AVG_BG)
    d.text((name_x + 6, y + 5), "Office Avg", font=f11b, fill=TEXT)
    for w, (pct, units) in enumerate(office_avg):
        d.text((week_x(w) + 4, y + 5), pct, font=f11b, fill=TEXT)
        d.text((week_x(w) + PCT_SUB_W + 2, y + 5), units, font=f10, fill=(90, 90, 90))
    y += ROW_H

    # Column header row (% / units repeated)
    d.rectangle([x, y, x + total_w - PAD * 2, y + HEADER_BAR_H], fill=COL_HEADER_BG)
    d.text((name_x + 6, y + 7), "Rep", font=f11b, fill=COL_HEADER_FG)
    for w in range(n_weeks):
        d.text((week_x(w) + 4, y + 7), "%", font=f11b, fill=COL_HEADER_FG)
        d.text((week_x(w) + PCT_SUB_W + 2, y + 7), "units", font=f10, fill=COL_HEADER_FG)
    y += HEADER_BAR_H

    # Rep rows
    for idx, (name, pairs) in enumerate(reps):
        if idx % 2 == 0:
            d.rectangle([x, y, x + total_w - PAD * 2, y + ROW_H], fill=ROW_BG)
        d.text((name_x + 6, y + 5), name[:26], font=f11, fill=TEXT)
        for w, (pct, units) in enumerate(pairs):
            if pct:
                # Band-color the % sub-cell background, then text on top.
                bg = band_color_rgb(pct)
                if bg != (255, 255, 255):
                    d.rectangle([week_x(w), y, week_x(w) + PCT_SUB_W, y + ROW_H], fill=bg)
                d.text((week_x(w) + 4, y + 5), pct, font=f11, fill=TEXT)
            if units:
                d.text((week_x(w) + PCT_SUB_W + 2, y + 5), units, font=f10, fill=(90, 90, 90))
        y += ROW_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
