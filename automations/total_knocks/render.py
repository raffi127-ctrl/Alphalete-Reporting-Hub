"""Render — draw the Total Knocks tab as a PNG for the Slack post.

Reads the freshly-filled tab straight from the Sheet (so the image is a
faithful screenshot of the full 14-column table, in the exact order/values
the tab shows) and draws it with Pillow.

Cross-platform font lookup (Windows + macOS + Linux) — no hard-coded Mac paths.

Standalone:
    .venv/Scripts/python.exe -m automations.total_knocks.render 2026-05-28
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from automations.recruiting_report.fill import open_by_key
from automations.total_knocks.fill import SHEET_ID, TAB_TEST, TAB_PROD, HEADER_ROW

# ---- palette (amber / door theme, matching the Hub card #B45309) ----
TITLE_BG  = (180, 83, 9)       # #B45309
TITLE_FG  = (255, 255, 255)
HEADER_BG = (60, 47, 36)       # dark brown
HEADER_FG = (255, 255, 255)
ROW_BG_A  = (255, 255, 255)
ROW_BG_B  = (248, 244, 239)    # faint warm stripe
GRID      = (224, 214, 204)
TEXT      = (38, 34, 30)
NAME_FG   = (20, 18, 16)

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
    """First installed font that loads, across Windows + macOS + Linux."""
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


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text or "", font=font))


def render_table(header: list[str], rows: list[list[str]], target: dt.date,
                 out_dir: Path = OUT_DIR_DEFAULT) -> Path:
    """Draw the table to a PNG, return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    f_title = _font(26, bold=True)
    f_head  = _font(13, bold=True)
    f_cell  = _font(13)
    f_name  = _font(13, bold=True)

    probe = Image.new("RGB", (10, 10))
    d0 = ImageDraw.Draw(probe)
    ncol = len(header)
    col_w = []
    for ci in range(ncol):
        w = _text_w(d0, header[ci], f_head)
        for r in rows:
            w = max(w, _text_w(d0, r[ci] if ci < len(r) else "", f_cell))
        col_w.append(min(MAX_COL_W, max(MIN_COL_W, w + 2 * CELL_PAD_X)))

    table_w = sum(col_w)
    img_h = PAD + TITLE_H + HEADER_H + ROW_H * len(rows) + PAD
    img = Image.new("RGB", (table_w + 2 * PAD, img_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # Title bar.
    d.rectangle([PAD, PAD, PAD + table_w, PAD + TITLE_H], fill=TITLE_BG)
    title = f"TOTAL KNOCKS — {target.strftime('%B')} {target.day}, {target.year}"
    d.text((PAD + CELL_PAD_X, PAD + (TITLE_H - 26) // 2), title,
           font=f_title, fill=TITLE_FG)

    # Header row.
    y = PAD + TITLE_H
    x = PAD
    for ci in range(ncol):
        d.rectangle([x, y, x + col_w[ci], y + HEADER_H], fill=HEADER_BG)
        d.text((x + CELL_PAD_X, y + (HEADER_H - 13) // 2),
               header[ci], font=f_head, fill=HEADER_FG)
        x += col_w[ci]

    # Data rows.
    y += HEADER_H
    for ri, r in enumerate(rows):
        bg = ROW_BG_A if ri % 2 == 0 else ROW_BG_B
        d.rectangle([PAD, y, PAD + table_w, y + ROW_H], fill=bg)
        x = PAD
        for ci in range(ncol):
            val = r[ci] if ci < len(r) else ""
            font = f_name if ci == 1 else f_cell
            fg = NAME_FG if ci == 1 else TEXT
            # Right-align numeric count columns; ID (col 0), Rep, times stay left.
            if val.strip().isdigit() and ci != 0:
                tx = x + col_w[ci] - CELL_PAD_X - _text_w(d, val, font)
            else:
                tx = x + CELL_PAD_X
            d.text((tx, y + (ROW_H - 13) // 2), val, font=font, fill=fg)
            x += col_w[ci]
        y += ROW_H

    # Grid lines.
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

    out_path = out_dir / f"total_knocks_{target.isoformat()}.png"
    img.save(out_path)
    return out_path


def render_from_sheet(target: dt.date, *, tab: str = TAB_PROD,
                      sheet_id: str = SHEET_ID,
                      out_dir: Path = OUT_DIR_DEFAULT) -> Path:
    header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows found in tab {tab!r} to render.")
    return render_table(header, rows, target, out_dir=out_dir)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (title)")
    ap.add_argument("--test-tab", action="store_true",
                    help="read the '… - TEST' sandbox tab instead of prod")
    args = ap.parse_args()
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else dt.date.today() - dt.timedelta(days=1))
    tab = TAB_TEST if args.test_tab else TAB_PROD
    path = render_from_sheet(target, tab=tab)
    print(f"[total_knocks.render] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
