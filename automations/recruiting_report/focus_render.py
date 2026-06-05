"""Render a Daily Focus Report tab (e.g. the 'Carlos' tab) to faithful PNGs.

Reads the LIVE grid straight from the Sheets API via the report's existing
gspread client — values, cell background colors, text format (bold / size /
color), horizontal alignment, merged ranges, and the real column / row pixel
sizes — then redraws it with PIL. The image mirrors what's on the sheet.

Why redraw instead of export-to-PDF: the report's OAuth token is scoped to
``spreadsheets`` only (no Drive), so the Google PDF-export endpoint won't
authorize, and there's no PDF→PNG library in the env. PIL is already a
dependency (see ``fiber_activations/render.py``), so this needs nothing new
and runs the same on macOS and Windows.

Public entry points:
    render_tab(spreadsheet, tab_title, out_path) -> Path
        One PNG of the whole used range (cols A:T).
    render_tab_grouped(spreadsheet, tab_title, out_dir, prefix, per=3) -> [Path]
        Split into one PNG per ``per`` owner sections (default 3), so each
        image is easier to read. Sections are found by their col-C
        '<owner> Current Week' header — never by hardcoded rows.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

SS = 2                      # supersample factor, downscaled at the end
DEFAULT_COL_PX = 100        # Sheets default column width
DEFAULT_ROW_PX = 21         # Sheets default row height
DEFAULT_FONT_PT = 10        # Sheets default font size
MAX_COLS = 20               # the report only ever uses cols A:T
PAD_X = 3                   # cell horizontal text padding (sheet px)
SECTION_MARK = "current week"   # col-C header that starts each owner section

GRID = (218, 220, 224)      # Sheets default gridline gray
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


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


def _a1_col(n: int) -> str:
    """1-based column number → A1 letter (20 → 'T')."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _rgb(color: Optional[dict], default):
    """Sheets API color dict ({red,green,blue} as 0..1 floats) → 0-255 tuple.
    A missing/empty dict falls back to ``default`` (white bg, black text)."""
    if not color:
        return default
    return (
        round(color.get("red", 0) * 255),
        round(color.get("green", 0) * 255),
        round(color.get("blue", 0) * 255),
    )


def _looks_numeric(text: str) -> bool:
    t = text.strip().lstrip("$").rstrip("%").replace(",", "").replace("-", "", 1)
    return bool(t) and t.replace(".", "", 1).isdigit()


def fetch_grid(spreadsheet, tab_title: str) -> dict:
    """One Sheets API call: grid data for A:T of the tab, with the formats,
    merges, and column/row pixel sizes we need to redraw it. Returns the
    sheet dict (``sheets[0]``)."""
    quoted = "'" + tab_title.replace("'", "''") + "'"
    rng = f"{quoted}!A:{_a1_col(MAX_COLS)}"
    meta = spreadsheet.fetch_sheet_metadata(params={
        "ranges": [rng],
        "includeGridData": True,
        "fields": (
            "sheets(properties(title),merges,"
            "data(rowData(values(formattedValue,effectiveFormat("
            "backgroundColor,horizontalAlignment,textFormat("
            "bold,fontSize,foregroundColor)))),"
            "columnMetadata(pixelSize),rowMetadata(pixelSize)))"
        ),
    })
    sheets = meta.get("sheets", [])
    if not sheets:
        raise RuntimeError(f"Tab {tab_title!r} not found in the spreadsheet.")
    return sheets[0]


def _row_has_text(rd) -> bool:
    return any((v or {}).get("formattedValue") for v in rd.get("values", []))


def _last_used_row(row_data) -> int:
    last = -1
    for i, rd in enumerate(row_data):
        if _row_has_text(rd):
            last = i
    return last


def section_anchors(sheet: dict) -> List[int]:
    """0-indexed rows whose col C contains '... Current Week' — i.e. the first
    row of each owner section."""
    row_data = (sheet.get("data") or [{}])[0].get("rowData", []) or []
    anchors = []
    for i, rd in enumerate(row_data):
        vals = rd.get("values", []) or []
        if len(vals) > 2:
            txt = ((vals[2] or {}).get("formattedValue") or "").lower()
            if SECTION_MARK in txt:
                anchors.append(i)
    return anchors


def _render_window(sheet: dict, out_path: Path,
                   row_start: int = 0, row_end: Optional[int] = None) -> Path:
    """Render rowData[row_start:row_end] (0-indexed, end-exclusive) to a PNG."""
    out_path = Path(out_path)
    data = (sheet.get("data") or [{}])[0]
    full_rows = data.get("rowData", []) or []
    col_meta = data.get("columnMetadata", []) or []
    row_meta = data.get("rowMetadata", []) or []

    if row_end is None:
        row_end = len(full_rows)
    row_data = full_rows[row_start:row_end]
    nrows = len(row_data)
    if nrows == 0:
        raise RuntimeError("Nothing to render in the requested row window.")

    widths = [
        (col_meta[c].get("pixelSize", DEFAULT_COL_PX)
         if c < len(col_meta) else DEFAULT_COL_PX)
        for c in range(MAX_COLS)
    ]
    heights = [
        (row_meta[row_start + r].get("pixelSize", DEFAULT_ROW_PX)
         if row_start + r < len(row_meta) else DEFAULT_ROW_PX)
        for r in range(nrows)
    ]

    xs = [0]
    for w in widths:
        xs.append(xs[-1] + w)
    ys = [0]
    for h in heights:
        ys.append(ys[-1] + h)
    total_w, total_h = xs[-1], ys[-1]

    # merges → local window coords (offset by row_start, clip to window)
    merge_id: dict = {}
    anchors: dict = {}
    for idx, m in enumerate(sheet.get("merges", []) or []):
        r0 = m.get("startRowIndex", 0) - row_start
        r1 = m.get("endRowIndex", 0) - row_start
        c0, c1 = m.get("startColumnIndex", 0), m.get("endColumnIndex", 0)
        c0, c1 = max(0, c0), min(MAX_COLS, c1)
        r0, r1 = max(0, r0), min(nrows, r1)
        if c0 >= c1 or r0 >= r1:
            continue
        anchors[idx] = (r0, c0, r1, c1)
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                merge_id[(rr, cc)] = idx

    img = Image.new("RGB", (total_w * SS, total_h * SS), WHITE)
    d = ImageDraw.Draw(img)

    def cell(r, c):
        try:
            return (row_data[r].get("values", []) or [])[c] or {}
        except IndexError:
            return {}

    def fmt(r, c):
        return cell(r, c).get("effectiveFormat", {}) or {}

    def paint_bg(r0, c0, r1, c1, color):
        if color == WHITE:
            return
        d.rectangle(
            [xs[c0] * SS, ys[r0] * SS, xs[c1] * SS - 1, ys[r1] * SS - 1],
            fill=color,
        )

    painted = set()
    for r in range(nrows):
        for c in range(MAX_COLS):
            mid = merge_id.get((r, c))
            if mid is not None:
                if mid in painted:
                    continue
                painted.add(mid)
                r0, c0, r1, c1 = anchors[mid]
                paint_bg(r0, c0, r1, c1, _rgb(fmt(r0, c0).get("backgroundColor"), WHITE))
            else:
                paint_bg(r, c, r + 1, c + 1, _rgb(fmt(r, c).get("backgroundColor"), WHITE))

    def same_merge(a, b):
        ma, mb = merge_id.get(a), merge_id.get(b)
        return ma is not None and ma == mb

    for r in range(nrows):
        for c in range(MAX_COLS):
            x0, y0, x1, y1 = xs[c] * SS, ys[r] * SS, xs[c + 1] * SS, ys[r + 1] * SS
            if c + 1 >= MAX_COLS or not same_merge((r, c), (r, c + 1)):
                d.line([x1, y0, x1, y1], fill=GRID, width=1)
            if r + 1 >= nrows or not same_merge((r, c), (r + 1, c)):
                d.line([x0, y1, x1, y1], fill=GRID, width=1)
    d.line([0, 0, total_w * SS, 0], fill=GRID, width=1)
    d.line([0, 0, 0, total_h * SS], fill=GRID, width=1)

    done_text = set()
    for r in range(nrows):
        for c in range(MAX_COLS):
            mid = merge_id.get((r, c))
            if mid is not None:
                if mid in done_text:
                    continue
                done_text.add(mid)
                r0, c0, r1, c1 = anchors[mid]
            else:
                r0, c0, r1, c1 = r, c, r + 1, c + 1

            cv = cell(r0, c0)
            text = " ".join((cv.get("formattedValue") or "").split())
            if not text:
                continue
            cf = cv.get("effectiveFormat", {}) or {}
            tf = cf.get("textFormat", {}) or {}
            bold = bool(tf.get("bold"))
            pt = tf.get("fontSize", DEFAULT_FONT_PT) or DEFAULT_FONT_PT
            fg = _rgb(tf.get("foregroundColor"), BLACK)
            font = _font(round(pt * 1.33 * SS), bold=bold)

            align = cf.get("horizontalAlignment")
            if not align:
                align = "RIGHT" if _looks_numeric(text) else "LEFT"

            avail_c1 = c1
            if align == "LEFT" and mid is None:
                cc = c1
                while (cc < MAX_COLS
                       and merge_id.get((r0, cc)) is None
                       and not (cell(r0, cc).get("formattedValue") or "").strip()):
                    avail_c1 = cc + 1
                    cc += 1
            box_x0, box_x1 = xs[c0] * SS, xs[avail_c1] * SS
            box_y0, box_y1 = ys[r0] * SS, ys[r1] * SS

            max_w = (box_x1 - box_x0) - 2 * PAD_X * SS
            txt = text
            while txt and d.textlength(txt, font=font) > max_w:
                txt = txt[:-1]
            if not txt:
                continue

            tw = d.textlength(txt, font=font)
            asc, desc = font.getmetrics()
            th = asc + desc
            ty = box_y0 + ((box_y1 - box_y0) - th) / 2
            if align == "RIGHT":
                tx = box_x1 - PAD_X * SS - tw
            elif align == "CENTER":
                tx = box_x0 + ((box_x1 - box_x0) - tw) / 2
            else:
                tx = box_x0 + PAD_X * SS
            d.text((tx, ty), txt, font=font, fill=fg)

    final = img.resize((total_w, total_h), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path)
    return out_path


def render_tab(spreadsheet, tab_title: str, out_path: Path) -> Path:
    """Render the whole used range of ``tab_title`` (cols A:T) to one PNG."""
    sheet = fetch_grid(spreadsheet, tab_title)
    last = _last_used_row((sheet.get("data") or [{}])[0].get("rowData", []) or [])
    if last < 0:
        raise RuntimeError(f"Tab {tab_title!r} appears empty — nothing to render.")
    return _render_window(sheet, out_path, 0, last + 1)


def render_tab_grouped(spreadsheet, tab_title: str, out_dir: Path,
                       prefix: str, per: int = 3) -> List[Path]:
    """Render ``tab_title`` split into one PNG per ``per`` owner sections.

    Each owner section is found by its col-C 'Current Week' header, so the
    split survives row insertions / template changes. The first image also
    includes any rows above the first section; the last runs to the final
    used row. Returns the PNG paths in top-to-bottom order.
    """
    out_dir = Path(out_dir)
    sheet = fetch_grid(spreadsheet, tab_title)
    row_data = (sheet.get("data") or [{}])[0].get("rowData", []) or []
    last = _last_used_row(row_data)
    if last < 0:
        raise RuntimeError(f"Tab {tab_title!r} appears empty — nothing to render.")
    end = last + 1

    anchors = [a for a in section_anchors(sheet) if a < end]
    if not anchors:
        # No detectable sections — fall back to a single full render.
        return [_render_window(sheet, out_dir / f"{prefix}-1.png", 0, end)]

    paths: List[Path] = []
    n_groups = (len(anchors) + per - 1) // per
    for g in range(n_groups):
        first_anchor = anchors[g * per]
        # group 0 starts at row 0 to keep any header above section 1
        row_start = 0 if g == 0 else first_anchor
        nxt = (g + 1) * per
        row_end = anchors[nxt] if nxt < len(anchors) else end
        out = out_dir / f"{prefix}-{g + 1}.png"
        paths.append(_render_window(sheet, out, row_start, row_end))
    return paths
