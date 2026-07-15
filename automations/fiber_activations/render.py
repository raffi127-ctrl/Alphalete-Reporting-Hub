"""Render the blue (Raf) and orange (Country) tables from the 'Captainship
Activations' tab as PNGs that mirror the sheet, for the daily Slack post in
#level10-alphalete.

Two images per run:
  - 'Fiber Activations Report {M.D}.png'            (blue):
        main weekly table (cols A-L, header + last 9 WE rows)
        + the 4 secondary tables below it (RAF CAPTAIN OVERRIDES,
          Captainship Metrics, New Internet 60 day Churn %,
          New Internet Activation %)
  - 'Country Fiber Activations Report {M.D}.png'    (orange):
        Country weekly table (cols Q-Z, header + last 9 WE rows)

Anchors are resolved by label (the 'Last 4 week AVG' row in col A) and the
'WE' header cell, so the render survives the weekly row insertion — no
hardcoded rows. The secondary block is read at avg_row+3 .. avg_row+19 with
its real merges, so it tracks the insert too.

Colors mirror the live sheet's effective cell colors (probed 2026-05-30),
desaturated a little so the image reads softer than the raw sheet. Rendered
at 2x then downscaled (LANCZOS) for crisp text and borders.
"""
from __future__ import annotations

import colorsys
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

AVG_LABEL = "Last 4 week AVG"
N_ROWS = 9            # trailing WE rows in the main table
SEC_FROM = 3          # secondary block starts at avg_row + 3
SEC_TO = 19           # ... through avg_row + 19 (inclusive)
SS = 2               # supersample factor

WHITE = (255, 255, 255)
TEXT = (20, 20, 20)
GRID = (120, 122, 138)


def _soften(rgb, s_mul=1.0, v_mul=1.0):
    """Pull a color toward calmer saturation/value (HSV) so it reads softer."""
    r, g, b = (c / 255 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb(h, min(1, s * s_mul), min(1, v * v_mul))
    return (round(r * 255), round(g * 255), round(b * 255))


# ---- palette (sheet hex, desaturated) --------------------------------------
BLUE_HEADER = _soften((137, 137, 235), 0.80)   # #8989EB
BLUE_WE_BG = _soften((196, 195, 247), 0.85)    # #C4C3F7
BLUE_WE_FG = (7, 55, 99)                        # #073763
BLUE_DAY_BG = _soften((232, 231, 252), 0.90)   # #E8E7FC
BLUE_I_BG = _soften((137, 137, 235), 0.80)     # col I accent

ORANGE_HEADER = _soften((255, 153, 0), 0.58, 0.95)  # #FF9900 -> muted
ORANGE_WE_BG = _soften((249, 203, 156), 0.80)        # #F9CB9C
ORANGE_WE_FG = (150, 80, 5)                           # #B45F06-ish
ORANGE_DAY_BG = WHITE
ORANGE_YZ_BG = _soften((255, 153, 0), 0.58, 0.95)

# Secondary-table palette (grays/green are already calm; keep near-original).
SEC_TITLE_BG = (102, 102, 102)   # #666666
SEC_GRAY_BG = (183, 183, 183)    # #B7B7B7
SEC_LIGHT_BG = (239, 239, 239)   # #EFEFEF
SEC_GREEN_BG = (182, 215, 168)   # #B6D7A8

# ---- layout (logical units; ×SS at draw time) ------------------------------
PAD = 14
TITLE_H = 44
HEADER_H = 52
ROW_H = 30
BAND_GAP = 26
SEC_ROW_H = 26

BLUE_COLS = [
    ("A", "WE", 92), ("B", "Wed", 60), ("C", "Thu", 60), ("D", "Fri", 60),
    ("E", "Sat", 60), ("F", "Sun", 60), ("G", "Mon", 60), ("H", "Tue", 60),
    ("I", "Total EOW\nCaptainship Sales", 118), ("J", "Activations", 90),
    ("K", "Captainship\npayout", 96), ("L", "% activated\nvs last week", 104),
]
ORANGE_COLS = [
    ("Q", "WE", 92), ("R", "Wed", 62), ("S", "Thu", 62), ("T", "Fri", 62),
    ("U", "Sat", 62), ("V", "Sun", 62), ("W", "Mon", 62),
    ("X", "Tue / Total\nActivations", 96), ("Y", "Total\nCountry Sales", 110),
    ("Z", "Estimated\nRevenue", 104),
]
# Secondary band column widths, cols A..I (A and F are spacers).
SEC_COL_W = [16, 120, 120, 95, 95, 20, 110, 112, 92]


def _font(size: int, bold: bool = False):
    """Cross-platform TrueType lookup (Windows + macOS + Linux), default last."""
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _idx(letter: str) -> int:
    return ord(letter) - ord("A")


def _lum(rgb) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _find_anchors(ws):
    """Return (header_row, [9 data rows], avg_row) by label, not index."""
    col_a = ws.col_values(1)
    avg_row = header_row = None
    for i, v in enumerate(col_a, 1):
        s = (v or "").strip()
        if s == "WE" and header_row is None:
            header_row = i
        if s == AVG_LABEL:
            avg_row = i
            break
    if header_row is None or avg_row is None:
        raise RuntimeError("Couldn't locate 'WE' header row and/or "
                           f"'{AVG_LABEL}' row in col A.")
    first = max(header_row + 1, avg_row - N_ROWS)
    return header_row, list(range(first, avg_row)), avg_row


def _read_block(ws, header_row, data_rows, start_col, end_col):
    last, first = data_rows[-1], data_rows[0]
    hdr = ws.get(f"{start_col}{header_row}:{end_col}{header_row}",
                 value_render_option="FORMATTED_VALUE")
    body = ws.get(f"{start_col}{first}:{end_col}{last}",
                  value_render_option="FORMATTED_VALUE")
    return (hdr[0] if hdr else []), body


def _read_secondary(ws, avg_row):
    """Read the 4 secondary tables (cols A-I) + their merges, anchored to AVG."""
    r0 = avg_row + SEC_FROM      # absolute 1-indexed first row
    r1 = avg_row + SEC_TO        # absolute 1-indexed last row
    sh = ws.spreadsheet
    meta = sh.fetch_sheet_metadata(params={
        "ranges": [f"'{ws.title}'!A{r0}:I{r1}"],
        "fields": "sheets("
                  "data.rowData.values("
                  "effectiveFormat.backgroundColor,"
                  "effectiveFormat.textFormat.bold,formattedValue),"
                  "merges)",
    })
    sheet = meta["sheets"][0]
    grid = sheet.get("data", [{}])[0].get("rowData", [])

    cells = {}  # (r_off, c) -> {bg, bold, val}
    for r_off, rd in enumerate(grid):
        for c, cell in enumerate(rd.get("values", [])):
            bg = cell.get("effectiveFormat", {}).get("backgroundColor")
            rgb = None
            if bg:
                rgb = (round(bg.get("red", 0) * 255),
                       round(bg.get("green", 0) * 255),
                       round(bg.get("blue", 0) * 255))
            cells[(r_off, c)] = {
                "bg": rgb,
                "bold": cell.get("effectiveFormat", {})
                            .get("textFormat", {}).get("bold", False),
                "val": cell.get("formattedValue", ""),
            }

    # Merges intersecting the region → top-left span map + covered set.
    topleft, covered = {}, set()
    for m in sheet.get("merges", []):
        mr0, mr1 = m["startRowIndex"], m["endRowIndex"]       # 0-indexed abs
        mc0, mc1 = m["startColumnIndex"], m["endColumnIndex"]
        if mr0 < (r0 - 1) or mr0 > (r1 - 1):
            continue
        rr, cc = mr0 - (r0 - 1), mc0
        topleft[(rr, cc)] = (mr1 - mr0, mc1 - mc0)
        for r in range(mr0, mr1):
            for c in range(mc0, mc1):
                if (r - (r0 - 1), c) != (rr, cc):
                    covered.add((r - (r0 - 1), c))
    n_rows = (r1 - r0) + 1
    return cells, topleft, covered, n_rows


def _draw_wrapped(d, text, box, font, fill):
    x0, y0, x1, y1 = box
    lines = str(text).split("\n")
    line_h = font.size + 3 * SS
    ty = y0 + ((y1 - y0) - line_h * len(lines)) / 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text((x0 + ((x1 - x0) - w) / 2, ty), ln, font=font, fill=fill)
        ty += line_h


def _draw_weekly_band(d, x0, y0, *, title, cols, body, header_bg, we_bg,
                      we_fg, day_bg, accent_cols, accent_bg, f_title, f_hdr,
                      f_cell, f_cell_b):
    """Draw title + header + data rows for a weekly table. Returns band width."""
    band_w = sum(w for _, _, w in cols) * SS
    base = _idx(cols[0][0])

    # Title bar.
    d.rectangle([x0, y0, x0 + band_w, y0 + TITLE_H * SS], fill=header_bg)
    _draw_wrapped(d, title, (x0, y0, x0 + band_w, y0 + TITLE_H * SS),
                  f_title, WHITE)
    y = y0 + TITLE_H * SS

    # Header row.
    cx = x0
    for (_letter, disp, w) in cols:
        d.rectangle([cx, y, cx + w * SS, y + HEADER_H * SS],
                    fill=header_bg, outline=GRID, width=SS)
        _draw_wrapped(d, disp, (cx, y, cx + w * SS, y + HEADER_H * SS),
                      f_hdr, TEXT)
        cx += w * SS
    y += HEADER_H * SS

    # Data rows.
    for row_vals in body:
        cx = x0
        for (letter, _disp, w) in cols:
            i = _idx(letter) - base
            val = row_vals[i] if i < len(row_vals) else ""
            if letter == cols[0][0]:
                bg, fg, fnt = we_bg, we_fg, f_cell_b
            elif letter in accent_cols:
                bg, fg, fnt = accent_bg, WHITE, f_cell_b
            else:
                bg, fg, fnt = day_bg, TEXT, f_cell
            d.rectangle([cx, y, cx + w * SS, y + ROW_H * SS],
                        fill=bg, outline=GRID, width=SS)
            if val:
                _draw_wrapped(d, val, (cx, y, cx + w * SS, y + ROW_H * SS),
                              fnt, fg)
            cx += w * SS
        y += ROW_H * SS
    return band_w


def _draw_secondary_band(d, x0, y0, cells, topleft, covered, n_rows,
                         f_sec, f_sec_b):
    """Draw the 4 secondary tables mirroring bg/bold/merges. Cells that are
    blank AND white are left empty (no border) so only real tables show."""
    xpos = [x0]
    for w in SEC_COL_W:
        xpos.append(xpos[-1] + w * SS)
    for r in range(n_rows):
        y = y0 + r * SEC_ROW_H * SS
        for c in range(len(SEC_COL_W)):
            if (r, c) in covered:
                continue
            cell = cells.get((r, c), {})
            val = cell.get("val", "")
            bg = cell.get("bg")
            is_white = (bg is None) or (bg == WHITE)
            if is_white and not val:
                continue  # spacer / empty -> leave blank
            rowspan, colspan = topleft.get((r, c), (1, 1))
            x1 = xpos[min(c + colspan, len(SEC_COL_W))]
            y1 = y0 + min(r + rowspan, n_rows) * SEC_ROW_H * SS
            fill = bg if bg else WHITE
            d.rectangle([xpos[c], y, x1, y1], fill=fill, outline=GRID, width=SS)
            if val:
                fg = WHITE if _lum(fill) < 140 else TEXT
                fnt = f_sec_b if cell.get("bold") else f_sec
                _draw_wrapped(d, val, (xpos[c], y, x1, y1), fnt, fg)


def _new_canvas(w, h):
    img = Image.new("RGB", (w * SS, h * SS), WHITE)
    return img, ImageDraw.Draw(img)


def _fonts():
    return {
        "title": _font(18 * SS, bold=True),
        "hdr": _font(11 * SS, bold=True),
        "cell": _font(12 * SS),
        "cell_b": _font(12 * SS, bold=True),
        "sec": _font(11 * SS),
        "sec_b": _font(11 * SS, bold=True),
    }


def _render_blue(ws, today, out_path, title):
    header_row, data_rows, avg_row = _find_anchors(ws)
    _, body = _read_block(ws, header_row, data_rows, "A", "L")
    cells, topleft, covered, n_sec = _read_secondary(ws, avg_row)

    main_w = sum(w for _, _, w in BLUE_COLS)
    sec_w = sum(SEC_COL_W)
    total_w = max(main_w, sec_w) + PAD * 2
    total_h = (TITLE_H + HEADER_H + ROW_H * len(body)
               + BAND_GAP + SEC_ROW_H * n_sec + PAD * 2)

    img, d = _new_canvas(total_w, total_h)
    f = _fonts()
    x0 = PAD * SS
    _draw_weekly_band(
        d, x0, PAD * SS, title=title, cols=BLUE_COLS, body=body,
        header_bg=BLUE_HEADER, we_bg=BLUE_WE_BG, we_fg=BLUE_WE_FG,
        day_bg=BLUE_DAY_BG, accent_cols={"I"}, accent_bg=BLUE_I_BG,
        f_title=f["title"], f_hdr=f["hdr"], f_cell=f["cell"],
        f_cell_b=f["cell_b"])
    sec_y = (PAD + TITLE_H + HEADER_H + ROW_H * len(body) + BAND_GAP) * SS
    _draw_secondary_band(d, x0, sec_y, cells, topleft, covered, n_sec,
                         f["sec"], f["sec_b"])

    img = img.resize((total_w, total_h), Image.LANCZOS)
    img.save(out_path)
    return out_path


def _render_orange(ws, today, out_path, title):
    header_row, data_rows, _ = _find_anchors(ws)
    _, body = _read_block(ws, header_row, data_rows, "Q", "Z")

    total_w = sum(w for _, _, w in ORANGE_COLS) + PAD * 2
    total_h = TITLE_H + HEADER_H + ROW_H * len(body) + PAD * 2

    img, d = _new_canvas(total_w, total_h)
    f = _fonts()
    _draw_weekly_band(
        d, PAD * SS, PAD * SS, title=title, cols=ORANGE_COLS, body=body,
        header_bg=ORANGE_HEADER, we_bg=ORANGE_WE_BG, we_fg=ORANGE_WE_FG,
        day_bg=ORANGE_DAY_BG, accent_cols={"Y", "Z"}, accent_bg=ORANGE_YZ_BG,
        f_title=f["title"], f_hdr=f["hdr"], f_cell=f["cell"],
        f_cell_b=f["cell_b"])

    img = img.resize((total_w, total_h), Image.LANCZOS)
    img.save(out_path)
    return out_path


def render_both(ws, today: dt.date, out_dir: Path) -> dict:
    """Render both PNGs. Returns {'fiber': Path, 'country': Path}. The file
    stems double as the Slack post names (post name == PNG name)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = f"{today.month}.{today.day}"
    fiber_name = f"Fiber Activations Report {md}"
    country_name = f"Country Fiber Activations Report {md}"
    return {
        "fiber": _render_blue(ws, today, out_dir / f"{fiber_name}.png",
                              fiber_name),
        "country": _render_orange(ws, today, out_dir / f"{country_name}.png",
                                  country_name),
    }
