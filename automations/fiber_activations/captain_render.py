"""Render the 6 PNGs for the per-captain workbook:
  - one VIOLET table per captain (cols A–L, the 'Captainship Payout' col K is
    OMITTED from the image only — it stays in the sheet for captains to fill).
  - one ORANGE country table (cols Q–Z), identical across tabs → rendered once.

ROW WINDOW (render-only, per table): show the last 8 WE rows that ACTUALLY HAVE
DATA in that table (7 closed + the in-progress week is the steady state). Before
8 weeks of history exist, show only the data-bearing rows, capped at 8 — so the
violet table (today only the current WE has data) shows a single row and grows
on its own each Wednesday, while the orange table (6 weeks loaded) shows 6. This
is purely cosmetic: it changes which rows are DRAWN, not the sheet, the fill, or
which rows exist.

The AVG row (row 8) is drawn ONLY when that table has >=4 CLOSED weeks of data
(data-bearing WE rows excluding the in-progress week) — so it appears once the
average is meaningful and never shows the #DIV/0! it would before then. Decided
per table: today the orange country table shows it (5 closed), the captain violet
doesn't yet (0 closed).

Each PNG MIRRORS the sheet's own effective cell colors (read via the API), so
every captain's distinct gama AND the conditional-format rolling-4 highlight
render correctly without hardcoding per-captain palettes. Reuses render.py's
canvas / fonts / layout constants.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image

from automations.fiber_activations import render as R
from automations.fiber_activations import captains as C

WINDOW = 8  # max WE rows drawn (7 closed + current, once history exists)

# Violet columns WITHOUT K (Captainship payout) — K omitted from the PNG only.
CAPTAIN_COLS = [c for c in R.BLUE_COLS if c[0] != "K"]
COUNTRY_COLS = R.ORANGE_COLS  # Q–Z, unchanged

# Columns whose non-empty value means "this WE row has data" for that table.
# Violet: day cells B–H + EOW I (J is a formula → excluded; K skipped; L is %).
# Orange: day cells R–X + Total Country Sales Y (Z is the revenue formula).
CAPTAIN_DETECT = ("B", "I")
COUNTRY_DETECT = ("R", "Y")


def _hex_to_rgb(bg):
    if not bg:
        return R.WHITE
    return (round(bg.get("red", 0) * 255), round(bg.get("green", 0) * 255),
            round(bg.get("blue", 0) * 255))


def _find_we_and_avg(ws):
    col_a = ws.col_values(1)
    header_row = avg_row = None
    for i, v in enumerate(col_a, 1):
        s = (v or "").strip()
        if s == "WE" and header_row is None:
            header_row = i
        if s == R.AVG_LABEL:
            avg_row = i
            break
    if header_row is None or avg_row is None:
        raise RuntimeError(f"Couldn't find 'WE' header and/or '{R.AVG_LABEL}' "
                           f"in col A of {ws.title!r}.")
    return header_row, avg_row


def _data_rows(ws, header_row, avg_row, detect):
    """All WE rows (top→bottom) that have data in `detect` cols. Falls back to
    the current row if none have data yet."""
    first, last = header_row + 1, avg_row - 1
    if last < first:
        return []
    d0, d1 = detect
    vals = ws.get(f"{d0}{first}:{d1}{last}",
                  value_render_option="UNFORMATTED_VALUE")
    rows = []
    for off, row in enumerate(vals):
        if any(str(c).strip() not in ("", "None") for c in row):
            rows.append(first + off)
    return rows or [last]


def _render_mirror(ws, today, out_path: Path, title: str, cols, detect,
                   with_secondary: bool = False) -> Path:
    """Draw title + header + the data-bearing WE rows (≤8), each cell filled with
    its real effective bg from the sheet. Skips columns not in `cols`.

    When `with_secondary` is set (captain violet tables only), the 4 secondary
    tables below the AVG row (overrides / metrics / churn + activation tiers) are
    rendered underneath — same region/process as Raf's render.py, mirroring each
    captain's real cell colors. Country (orange) stays single-band."""
    header_row, avg_row = _find_we_and_avg(ws)
    all_rows = _data_rows(ws, header_row, avg_row, detect)
    window = all_rows[-WINDOW:]
    # Closed weeks = data rows excluding the in-progress (most recent) one.
    # Show the AVG row only once >=4 closed weeks exist (avoids #DIV/0!).
    show_avg = (len(all_rows) - 1) >= 4
    draw_rows = window + ([avg_row] if show_avg else [])

    start, end = cols[0][0], cols[-1][0]
    span_last = draw_rows[-1]
    sh = ws.spreadsheet
    meta = sh.fetch_sheet_metadata(params={
        "ranges": [f"'{ws.title}'!{start}{header_row}:{end}{span_last}"],
        "fields": "sheets(data.rowData.values(formattedValue,"
                  "effectiveFormat.backgroundColor,effectiveFormat.textFormat.bold))",
    })
    grid = meta["sheets"][0].get("data", [{}])[0].get("rowData", [])
    base = R._idx(start)

    def cell(rownum, letter):
        r_off = rownum - header_row
        i = R._idx(letter) - base
        row = grid[r_off].get("values", []) if 0 <= r_off < len(grid) else []
        return row[i] if i < len(row) else {}

    # Secondary block (captain tables only) — read it up front so the canvas is
    # sized to fit it. Same anchors/region as Raf (avg_row+3 .. avg_row+19).
    sec = None
    if with_secondary:
        s_cells, s_topleft, s_covered, n_sec = R._read_secondary(ws, avg_row)
        sec = (s_cells, s_topleft, s_covered, n_sec)

    band_w = sum(w for _, _, w in cols)
    main_w = band_w + R.PAD * 2
    total_w = (max(band_w, sum(R.SEC_COL_W)) + R.PAD * 2) if sec else main_w
    total_h = R.TITLE_H + R.HEADER_H + R.ROW_H * len(draw_rows) + R.PAD * 2
    if sec:
        total_h += R.BAND_GAP + R.SEC_ROW_H * sec[3]
    img, d = R._new_canvas(total_w, total_h)
    f = R._fonts()
    x0 = R.PAD * R.SS

    # Title bar — colored from the header row's first cell.
    title_bg = _hex_to_rgb(cell(header_row, start).get(
        "effectiveFormat", {}).get("backgroundColor"))
    y = R.PAD * R.SS
    d.rectangle([x0, y, x0 + band_w * R.SS, y + R.TITLE_H * R.SS], fill=title_bg)
    R._draw_wrapped(d, title, (x0, y, x0 + band_w * R.SS, y + R.TITLE_H * R.SS),
                    f["title"], R.WHITE if R._lum(title_bg) < 140 else R.TEXT)
    y += R.TITLE_H * R.SS

    # Header row.
    cx = x0
    for (letter, disp, w) in cols:
        bg = _hex_to_rgb(cell(header_row, letter).get(
            "effectiveFormat", {}).get("backgroundColor"))
        d.rectangle([cx, y, cx + w * R.SS, y + R.HEADER_H * R.SS], fill=bg,
                    outline=R.GRID, width=R.SS)
        R._draw_wrapped(d, disp, (cx, y, cx + w * R.SS, y + R.HEADER_H * R.SS),
                        f["hdr"], R.WHITE if R._lum(bg) < 140 else R.TEXT)
        cx += w * R.SS
    y += R.HEADER_H * R.SS

    # The data-bearing WE rows (≤8), plus the AVG row when >=4 closed weeks.
    for rownum in draw_rows:
        cx = x0
        for (letter, _disp, w) in cols:
            cl = cell(rownum, letter)
            bg = _hex_to_rgb(cl.get("effectiveFormat", {}).get("backgroundColor"))
            val = cl.get("formattedValue", "")
            d.rectangle([cx, y, cx + w * R.SS, y + R.ROW_H * R.SS], fill=bg,
                        outline=R.GRID, width=R.SS)
            if val:
                fg = R.WHITE if R._lum(bg) < 140 else R.TEXT
                fnt = f["cell_b"] if cl.get("effectiveFormat", {}).get(
                    "textFormat", {}).get("bold") else f["cell"]
                R._draw_wrapped(d, val, (cx, y, cx + w * R.SS, y + R.ROW_H * R.SS),
                                fnt, fg)
            cx += w * R.SS
        y += R.ROW_H * R.SS

    # Secondary band underneath (captain tables only), after a gap — mirrors the
    # 4 tables' real bg/bold/merges via Raf's generic drawer.
    if sec:
        s_cells, s_topleft, s_covered, n_sec = sec
        sec_y = y + R.BAND_GAP * R.SS
        R._draw_secondary_band(d, x0, sec_y, s_cells, s_topleft, s_covered,
                               n_sec, f["sec"], f["sec_b"])

    img = img.resize((total_w, total_h), Image.LANCZOS)
    img.save(out_path)
    return out_path


def render_all(sh, today: dt.date, out_dir: Path) -> dict:
    """Render all 6 PNGs. Returns {label: Path}. Country rendered once (it's
    identical across all tabs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = f"{today.month}.{today.day}"
    out = {}
    for cap in C.CAPTAINS:
        ws = sh.worksheet(cap.tab)
        name = f"Captainship Activations - {cap.team} by {md}"
        out[cap.team] = _render_mirror(ws, today, out_dir / f"{name}.png",
                                       name, CAPTAIN_COLS, CAPTAIN_DETECT,
                                       with_secondary=True)
    ws0 = sh.worksheet(C.CAPTAINS[0].tab)
    cname = f"Country Captainship Activations by {md}"
    out["Country"] = _render_mirror(ws0, today, out_dir / f"{cname}.png",
                                    cname, COUNTRY_COLS, COUNTRY_DETECT)
    return out
