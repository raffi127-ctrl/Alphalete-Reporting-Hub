"""Render — draw the report's two PNGs from the freshly-filled tab.

  1. Total Knocks  — columns A–N, in the tab's order (First Knock asc),
     amber theme. Posted to Slack as 'Total Knocks' (🚪).
  2. Time Gaps     — columns ID, Rep, First Knock, Last Knock, Gaps,
     Total Gaps (min), sorted by Total Gaps (min) DESC, teal theme (a
     different header colour so it reads as a separate metric). Posted as
     'Time Gaps' (🕐).

Both read straight from the Sheet so they're faithful screenshots of the tab.
Cross-platform font lookup (Windows + macOS + Linux) — no hard-coded Mac paths.

Standalone:
    .venv/Scripts/python.exe -m automations.total_knocks.render 2026-05-28 [--test-tab]
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from automations.recruiting_report.fill import open_by_key
from automations.total_knocks.fill import SHEET_ID, TAB_TEST, TAB_PROD, HEADER_ROW
from automations.total_knocks.pull import (
    COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
    SHEET_COLUMNS,
    _norm,
)

# ---- themes (title bar / header row / alternating stripe) ----
THEME_AMBER = {        # Total Knocks (matches the Hub card #B45309)
    "title_bg": (180, 83, 9),
    "header_bg": (60, 47, 36),
    "stripe": (248, 244, 239),
}
THEME_TEAL = {         # Time Gaps — distinct colour (🕐)
    "title_bg": (13, 110, 139),
    "header_bg": (15, 52, 67),
    "stripe": (234, 243, 246),
}
TITLE_FG  = (255, 255, 255)
HEADER_FG = (255, 255, 255)
ROW_BG_A  = (255, 255, 255)
GRID      = (224, 214, 204)
TEXT      = (38, 34, 30)
NAME_FG   = (20, 18, 16)

# Total Knocks shows columns A–N (the first 14); Gaps / Total Gaps are excluded.
TOTAL_KNOCKS_NCOL = 14
# Time Gaps shows just these, in this order.
TIME_GAPS_COLUMNS = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                     COL_GAPS, COL_TOTAL_GAPS]

# ---- layout ----
PAD        = 16
TITLE_H    = 52
HEADER_H   = 40
ROW_H      = 28
CELL_PAD_X = 4
MIN_COL_W  = 26
MAX_COL_W  = 320
OUT_DIR_DEFAULT = Path("output")


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _read_table(sheet_id: str, tab: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, data_rows) from the tab — only non-empty data rows."""
    sh = open_by_key(sheet_id)
    ws = sh.worksheet(tab)
    vals = ws.get_all_values()
    if not vals:
        return [], []
    header = vals[HEADER_ROW - 1]
    last_col = max((i for i, c in enumerate(header) if c.strip()), default=-1)
    header = header[:last_col + 1]
    rows = []
    for r in vals[HEADER_ROW:]:
        cells = (r + [""] * len(header))[:len(header)]
        if any(c.strip() for c in cells):
            rows.append(cells)
    return header, rows


def _table_from_rows(
    records: list[dict],
) -> tuple[list[str], list[list[str]]]:
    """Build the same (header, data_rows) shape `_read_table` returns, but from
    in-memory records keyed by SHEET_COLUMNS — no Sheet read.

    Used to render directly from a fresh pull (e.g. an impersonated single
    office) without writing a production tab. The header order and stringified
    cells mirror exactly what the filled tab would show, so the rendered image
    is identical to the Sheet-backed one.
    """
    header = list(SHEET_COLUMNS)
    rows: list[list[str]] = []
    for rec in records:
        cells = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
                 for c in header]
        if any(c.strip() for c in cells):
            rows.append(cells)
    return header, rows


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text or "", font=font))


def _draw(header: list[str], rows: list[list[str]], title: str, theme: dict,
          out_path: Path, name_col: int = 1) -> Path:
    """Generic table → PNG. `name_col` (0-based) is left-aligned + bold."""
    f_title = _font(26, bold=True)
    f_head  = _font(13, bold=True)
    f_cell  = _font(13)
    f_name  = _font(13, bold=True)

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    ncol = len(header)
    col_w = []
    for ci in range(ncol):
        w = _text_w(probe, header[ci], f_head)
        for r in rows:
            w = max(w, _text_w(probe, r[ci] if ci < len(r) else "", f_cell))
        col_w.append(min(MAX_COL_W, max(MIN_COL_W, w + 2 * CELL_PAD_X)))

    table_w = sum(col_w)
    img_h = PAD + TITLE_H + HEADER_H + ROW_H * len(rows) + PAD
    img = Image.new("RGB", (table_w + 2 * PAD, img_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.rectangle([PAD, PAD, PAD + table_w, PAD + TITLE_H], fill=theme["title_bg"])
    d.text((PAD + CELL_PAD_X, PAD + (TITLE_H - 26) // 2), title,
           font=f_title, fill=TITLE_FG)

    y, x = PAD + TITLE_H, PAD
    for ci in range(ncol):
        d.rectangle([x, y, x + col_w[ci], y + HEADER_H], fill=theme["header_bg"])
        d.text((x + CELL_PAD_X, y + (HEADER_H - 13) // 2),
               header[ci], font=f_head, fill=HEADER_FG)
        x += col_w[ci]

    y += HEADER_H
    for ri, r in enumerate(rows):
        bg = ROW_BG_A if ri % 2 == 0 else theme["stripe"]
        d.rectangle([PAD, y, PAD + table_w, y + ROW_H], fill=bg)
        x = PAD
        for ci in range(ncol):
            val = r[ci] if ci < len(r) else ""
            font = f_name if ci == name_col else f_cell
            fg = NAME_FG if ci == name_col else TEXT
            if val.strip().isdigit() and ci != 0:    # right-align counts (not ID)
                tx = x + col_w[ci] - CELL_PAD_X - _text_w(d, val, font)
            else:
                tx = x + CELL_PAD_X
            d.text((tx, y + (ROW_H - 13) // 2), val, font=font, fill=fg)
            x += col_w[ci]
        y += ROW_H

    x = PAD
    for ci in range(ncol + 1):
        d.line([x, PAD + TITLE_H, x, img_h - PAD], fill=GRID, width=1)
        if ci < ncol:
            x += col_w[ci]
    yy = PAD + TITLE_H
    d.line([PAD, yy, PAD + table_w, yy], fill=GRID, width=1)
    yy += HEADER_H
    for _ in range(len(rows) + 1):
        d.line([PAD, yy, PAD + table_w, yy], fill=GRID, width=1)
        yy += ROW_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _title_date(target: dt.date) -> str:
    return f"{target.strftime('%B')} {target.day}, {target.year}"


def render_total_knocks(target: dt.date, *, tab: str = TAB_PROD,
                        sheet_id: str = SHEET_ID,
                        out_dir: Path = OUT_DIR_DEFAULT,
                        rows: list[dict] | None = None) -> Path:
    """PNG 1 — columns A–N, in tab order (First Knock asc), amber theme.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them (sorted the same way fill.py orders the tab —
    First Knock asc) instead of reading the Sheet, so callers can render a
    fresh pull without writing a production tab. Default (None) preserves the
    exact Sheet-reading behaviour.
    """
    if rows is not None:
        from automations.total_knocks.fill import _sorted_rows
        header, rows = _table_from_rows(_sorted_rows(rows))
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    n = min(TOTAL_KNOCKS_NCOL, len(header))
    header = header[:n]
    rows = [r[:n] for r in rows]
    return _draw(header, rows, f"TOTAL KNOCKS — {_title_date(target)}",
                 THEME_AMBER, out_dir / f"total_knocks_{target.isoformat()}.png")


def _gap_min(v: str) -> int:
    v = (v or "").strip()
    return int(v) if v.isdigit() else -1


def _fmt_hm(v: str) -> str:
    """Minutes int → 'Xh Ym' (matching how Ownerville displays it, e.g. 79 ->
    '1h 19m', 180 -> '3h 0m'). Blank / non-numeric passes through unchanged."""
    v = (v or "").strip()
    if not v.isdigit():
        return v
    m = int(v)
    return f"{m // 60}h {m % 60}m"


def render_time_gaps(target: dt.date, *, tab: str = TAB_PROD,
                     sheet_id: str = SHEET_ID,
                     out_dir: Path = OUT_DIR_DEFAULT,
                     rows: list[dict] | None = None) -> Path:
    """PNG 2 — ID, Rep, First/Last Knock, Gaps, Total Gaps (min), sorted by
    Total Gaps (min) desc, teal theme. Total Gaps is shown as 'Xh Ym' (like
    Ownerville); the Sheet column itself stays in plain minutes.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them instead of reading the Sheet (this function does
    its own Total-Gaps-desc sort, so no pre-sort is needed). Default (None)
    preserves the exact Sheet-reading behaviour.
    """
    if rows is not None:
        header, rows = _table_from_rows(rows)
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    idx = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k and k not in idx:
            idx[k] = i
    missing = [c for c in TIME_GAPS_COLUMNS if _norm(c) not in idx]
    if missing:
        raise RuntimeError(f"Tab {tab!r} missing column(s) for Time Gaps: "
                           f"{missing}. Header: {header}")
    sel = [idx[_norm(c)] for c in TIME_GAPS_COLUMNS]
    sub = [[(r[i] if i < len(r) else "") for i in sel] for r in rows]
    tg_pos = TIME_GAPS_COLUMNS.index(COL_TOTAL_GAPS)
    # Sort by numeric minutes (desc) BEFORE formatting to 'Xh Ym'.
    sub.sort(key=lambda r: _gap_min(r[tg_pos]), reverse=True)
    for r in sub:
        r[tg_pos] = _fmt_hm(r[tg_pos])
    return _draw(list(TIME_GAPS_COLUMNS), sub,
                 f"TIME GAPS — {_title_date(target)}",
                 THEME_TEAL, out_dir / f"time_gaps_{target.isoformat()}.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (title)")
    ap.add_argument("--test-tab", action="store_true",
                    help="read the '… - TEST' sandbox tab instead of prod")
    args = ap.parse_args()
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else dt.date.today() - dt.timedelta(days=1))
    tab = TAB_TEST if args.test_tab else TAB_PROD
    p1 = render_total_knocks(target, tab=tab)
    p2 = render_time_gaps(target, tab=tab)
    print(f"[total_knocks.render] wrote {p1}")
    print(f"[total_knocks.render] wrote {p2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
