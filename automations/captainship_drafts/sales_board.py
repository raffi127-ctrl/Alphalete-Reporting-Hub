"""Section 1 of the Captainship drafts, sourced from the 'Alphalete ORG
Sales Board' sheet:

  * product_summary_image(captain, out) -> a PNG that looks EXACTLY like
    the sheet. We export the captain's Product Summary range to PDF via
    Google Sheets' own export endpoint (which renders it identically to
    the sheet — native colors, fonts, borders, merges), then rasterize +
    vertically stitch the pages into one seamless image (margins trimmed,
    no visible seams between the sub-charts).

  * units_image(captain, today, out) -> a PIL PNG of the Captainship
    Units block: name + the 'Total for week' group + the most-recent day
    group that has data (scanned left→right, last non-zero), found by the
    day-name headers (no hardcoded columns).

Row ranges per captain come from PS_ROWS / UNITS_ROWS (given by Megan).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import fitz   # PyMuPDF — PDF → PNG raster
import requests
from PIL import Image, ImageChops, ImageDraw

from automations.recruiting_report import fill as _rf
from automations.new_internet_churn.render import _font

SALES_BOARD_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
SALES_BOARD_TAB = "Alphalete ORG Sales Board"

# Product Summary ranges (inclusive sheet rows).
PS_ROWS = {
    "rafael": (197, 382), "carlos": (385, 499), "eveliz": (502, 603),
    "wayne": (606, 706), "starr": (710, 777), "aron": (781, 864),
    "khalil": (868, 939), "colten": (943, 1028), "jairo": (1034, 1097),
    "luis": (1101, 1142),
}

# Captainship Units ranges (inclusive sheet rows).
UNITS_ROWS = {
    "rafael": (1197, 1230), "carlos": (1233, 1247), "eveliz": (1250, 1258),
    "wayne": (1261, 1272), "starr": (1275, 1283), "aron": (1286, 1302),
    "khalil": (1305, 1315), "colten": (1318, 1335), "jairo": (1338, 1345),
    "luis": (1389, 1397),
}

# How many columns the Product Summary block spans (A..K). The daily +
# weekly tables top out at the 'Grand Total' / oldest WE column at K.
PS_END_COL = "K"

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")


def _open_ws():
    return _rf._client().open_by_key(SALES_BOARD_ID).worksheet(SALES_BOARD_TAB)


# --------------------------------------------------------------------------
# Range helpers for the screenshot capture (sheet_shot)
# --------------------------------------------------------------------------
def ps_range(captain_key: str) -> str:
    """Full Product Summary block range for a captain, A through the LAST
    'WE MM.DD' weekly-historical column (scanned from the block's own
    header cells — the historicals grow a column every week, so the end
    column is never hardcoded). Falls back to PS_END_COL if no WE headers
    are found."""
    from gspread.utils import rowcol_to_a1, a1_to_rowcol
    start, end = PS_ROWS[captain_key]
    block = _open_ws().get(f"{start}:{end}")   # row-only range -> used cols
    last = 0
    for row in block:
        for j, v in enumerate(row):
            if re.match(r"^WE \d", str(v).strip()):
                last = max(last, j + 1)        # 1-based column number
    floor_col = a1_to_rowcol(f"{PS_END_COL}1")[1]
    end_col = rowcol_to_a1(1, max(last, floor_col))[:-1]
    return f"A{start}:{end_col}{end}"


def units_day_columns(captain_key: str):
    """(day_name, first_col_letter, last_col_letter) of the most recent
    day group WITH DATA in the captain's Captainship Units block — same
    detection as units_image: day-name headers mark each 3-col group;
    keep the rightmost whose total-row 'This week' cell is non-zero."""
    from gspread.utils import rowcol_to_a1
    start, end = UNITS_ROWS[captain_key]
    grid = _open_ws().get(f"B{start}:W{end}")
    if not grid:
        raise ValueError(f"empty units range for {captain_key}")
    day_cols = {}
    for i, v in enumerate(grid[0]):
        if (v or "").strip() in _DAYS:
            day_cols[(v or "").strip()] = i
    total_row = grid[2:][-1] if len(grid) > 2 else []
    chosen = None
    for day in _DAYS:
        c = day_cols.get(day)
        if c is None:
            continue
        v = _to_num(total_row[c]) if c < len(total_row) else None
        if v:
            chosen = (day, c)
    if chosen is None:   # nothing filled yet (e.g. Monday AM) -> rightmost
        day = max(day_cols, key=lambda d: day_cols[d]) if day_cols else "Monday"
        chosen = (day, day_cols.get(day, 1))
    day_name, local = chosen
    first = local + 2            # local 0 == column B == column number 2
    return (day_name,
            rowcol_to_a1(1, first)[:-1], rowcol_to_a1(1, first + 2)[:-1])


# --------------------------------------------------------------------------
# Product Summary -> PNG (Google Sheets PDF export, rasterized + stitched)
# --------------------------------------------------------------------------
def _sheets_token() -> str:
    """Fresh OAuth access token for the Sheets account (spreadsheets scope).
    The docs.google.com PDF export accepts this Bearer token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(
        str(_rf.OAUTH_TOKEN_PATH), _rf.SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def _ps_pdf_bytes(start: int, end: int, end_col: str) -> bytes:
    ws = _open_ws()
    rng = f"A{start}:{end_col}{end}"
    url = (f"https://docs.google.com/spreadsheets/d/{ws.spreadsheet.id}/export"
           f"?format=pdf&gid={ws.id}&range={rng}"
           f"&portrait=false&fitw=true&gridlines=false"
           f"&printtitle=false&sheetnames=false&pagenum=false&fzr=false"
           f"&top_margin=0.05&bottom_margin=0.05"
           f"&left_margin=0.05&right_margin=0.05")
    r = requests.get(url, headers={"Authorization": f"Bearer {_sheets_token()}"},
                     timeout=60)
    r.raise_for_status()
    if "pdf" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"Sheets export did not return a PDF "
            f"(content-type={r.headers.get('content-type')!r}).")
    return r.content


def _trim_vertical(im: Image.Image) -> Image.Image:
    """Trim top/bottom near-white margins, keep full width so columns stay
    aligned when pages are stacked."""
    bg = Image.new(im.mode, im.size, (255, 255, 255))
    bbox = ImageChops.difference(im, bg).getbbox()
    if not bbox:
        return im
    return im.crop((0, bbox[1], im.width, bbox[3]))


def product_summary_image(captain, out_path: Path, *,
                          end_col: str = PS_END_COL, zoom: int = 2) -> Path:
    """Render the captain's Product Summary range to a single seamless PNG
    that matches the Google Sheets appearance."""
    start, end = PS_ROWS[captain.key]
    pdf = _ps_pdf_bytes(start, end, end_col)
    doc = fitz.open(stream=pdf, filetype="pdf")
    pages = []
    for pg in doc:
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        mode = "RGBA" if pix.alpha else "RGB"
        im = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        pages.append(_trim_vertical(im.convert("RGB")))
    doc.close()
    if not pages:
        raise RuntimeError(f"no PDF pages for {captain.key} product summary")

    w = max(p.width for p in pages)
    h = sum(p.height for p in pages)
    stitched = Image.new("RGB", (w, h), "white")
    y = 0
    for p in pages:
        stitched.paste(p, (0, y))
        y += p.height

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stitched.save(out_path)
    return out_path


# --------------------------------------------------------------------------
# Captainship Units -> PIL image
# --------------------------------------------------------------------------
_HDR_BG = (60, 60, 60)
_HDR_FG = (255, 255, 255)
_TOTAL_BG = (235, 235, 235)
_POS = (198, 239, 206)   # green-ish for positive delta
_NEG = (244, 199, 195)   # red-ish for negative delta
_GRID = (210, 210, 210)


def _to_num(s: str):
    s = (s or "").strip().replace(",", "").rstrip("%")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def units_image(captain, today: dt.date, out_path: Path) -> Path:
    """Render the captain's Captainship Units block as a PNG: name +
    'Total for week' group + the most-recent day group that has data."""
    start, end = UNITS_ROWS[captain.key]
    ws = _open_ws()
    grid = ws.get(f"B{start}:W{end}")  # row0 = day headers, row1 = subheaders
    if not grid:
        raise ValueError(f"empty units range for {captain.key}")

    hdr = grid[0]            # day-name labels at each 3-col group start
    day_cols = {}
    for i, v in enumerate(hdr):
        name = (v or "").strip()
        if name in _DAYS:
            day_cols[name] = i
    total_start = 1          # 'Total for week' group = cols C,D,E (local 1,2,3)

    data_rows = grid[2:]     # rep rows + the 'Captainship' total (last row)
    total_row = data_rows[-1] if data_rows else []

    # Most-recent day group WITH DATA: scan Mon..Sat, keep the rightmost
    # whose total-row 'This week' cell is non-zero.
    chosen = None
    for day in _DAYS:
        c = day_cols.get(day)
        if c is None:
            continue
        v = _to_num(total_row[c]) if c < len(total_row) else None
        if v:
            chosen = (day, c)
    if chosen is None:
        day = max(day_cols, key=lambda d: day_cols[d]) if day_cols else "Monday"
        chosen = (day, day_cols.get(day, 1))
    day_name, day_start = chosen

    groups = [("Total for week", total_start), (day_name, day_start)]
    col_specs = [("Rep", None)]
    for label, gs in groups:
        col_specs += [(f"{label}\nThis wk", gs),
                      ("Last wk", gs + 1), ("Δ", gs + 2)]

    NAME_W, NUM_W, ROW_H, HDR_H = 220, 96, 22, 38
    PAD = 10
    n_data = len(data_rows)
    width = NAME_W + NUM_W * 6 + PAD * 2
    height = HDR_H + ROW_H * (n_data + 1) + PAD * 2
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f = _font(11)
    fb = _font(11, bold=True)
    f13b = _font(13, bold=True)

    x0, y = PAD, PAD
    d.text((x0, y), f"{captain.display_name} — Captainship Units "
                    f"({day_name})", fill=(20, 20, 20), font=f13b)
    y += 20

    def col_x(i):
        return x0 if i == 0 else x0 + NAME_W + NUM_W * (i - 1)

    def col_w(i):
        return NAME_W if i == 0 else NUM_W

    for i, (cap, _src) in enumerate(col_specs):
        cx, cw = col_x(i), col_w(i)
        d.rectangle([cx, y, cx + cw, y + HDR_H], fill=_HDR_BG)
        for li, line in enumerate(cap.split("\n")):
            d.text((cx + 4, y + 4 + li * 13), line, fill=_HDR_FG, font=fb)
    y += HDR_H

    for r_i, row in enumerate(data_rows):
        is_total = (r_i == n_data - 1)
        base_bg = _TOTAL_BG if is_total else ("white" if r_i % 2 == 0
                                              else (246, 247, 250))
        name = (row[0] if row else "").strip()
        for i, (cap, src) in enumerate(col_specs):
            cx, cw = col_x(i), col_w(i)
            d.rectangle([cx, y, cx + cw, y + ROW_H], fill=base_bg)
            if i == 0:
                txt = name
            else:
                txt = (row[src] if src is not None and src < len(row) else "") or ""
                if cap == "Δ":
                    num = _to_num(txt)
                    if num is not None and num != 0:
                        d.rectangle([cx, y, cx + cw, y + ROW_H],
                                    fill=_POS if num > 0 else _NEG)
            limit = 30 if i == 0 else 16
            d.text((cx + 4, y + 5), str(txt)[:limit],
                   fill=(30, 30, 30), font=(fb if is_total else f))
        y += ROW_H

    for i in range(len(col_specs) + 1):
        gx = col_x(i) if i < len(col_specs) else width - PAD
        d.line([gx, PAD + 20, gx, height - PAD], fill=_GRID)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
