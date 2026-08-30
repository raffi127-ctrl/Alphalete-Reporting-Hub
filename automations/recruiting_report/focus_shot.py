"""Exact-sheet PNGs of the Daily Focus tabs.

WHY NOT focus_render: that module REDRAWS the grid with PIL, cell by cell. It
is close, but "close" is a losing game against Google's own layout engine —
borders, wrapped headers, merged labels and the black header bands each need
their own special case, and every fix is one more thing to keep true as the
template moves (2026-08-30: six rounds of border/header corrections and still
not right).

So this asks GOOGLE to render it, through the same Sheets PDF-export engine the
Org Sales Board screenshot email already uses in production
(org_sales_board.screenshot_email._export_png). What comes back is the sheet:
its borders, its fonts, its wrapping, its colours — because it IS the sheet.

The section's row range is still found by its col-C '<Owner> Current Week'
label, never by a row number, so it survives sections being added, removed or
reordered on the tab.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials

from automations.recruiting_report import focus_render
from automations.recruiting_report.fill import SCOPES, OAUTH_TOKEN_PATH
from automations.shared import sheets_export as _sx

# Raster DPI multiplier. The export is VECTOR, so this genuinely re-renders the
# text at more pixels rather than upscaling a small image.
RENDER_SCALE = 1.0

SECTION_MARK = focus_render.SECTION_MARK       # "current week"


def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def _col_letter(n: int) -> str:
    """1-indexed column number -> A1 letters."""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _section_owner(rd) -> str:
    """Owner name from a section's col-C header, or '' if not a header row."""
    vals = rd.get("values", []) or []
    if len(vals) <= 2:
        return ""
    txt = (vals[2] or {}).get("formattedValue") or ""
    low = txt.lower()
    if SECTION_MARK not in low:
        return ""
    return " ".join(txt[:low.index(SECTION_MARK)].split())


def section_index(sheet: dict) -> List[Tuple[str, int]]:
    """[(owner, 0-indexed anchor row)] top to bottom."""
    rows = (sheet.get("data") or [{}])[0].get("rowData", []) or []
    return [(o, i) for i, rd in enumerate(rows) if (o := _section_owner(rd))]


def section_range(sheet: dict, owner: str) -> str:
    """The A1 range covering one owner's section, both weeks.

    Current Week and Last Week sit on the SAME rows (Current ~A:J, Last ~L:T),
    so one full-width row window carries both — "a screenshot of current week
    and the one last week" (Raf, 2026-08-30). The right edge stops at the last
    column that actually carries something, so the tab's empty trailing columns
    are not exported as dead white space.
    """
    rows = (sheet.get("data") or [{}])[0].get("rowData", []) or []
    index = section_index(sheet)
    if not index:
        raise RuntimeError("No '<Owner> Current Week' headers in column C — "
                           "the template may have changed.")
    want = " ".join(owner.split()).lower()
    match = next(((p, r) for p, (n, r) in enumerate(index)
                  if n.lower() == want), None)
    if match is None:
        raise RuntimeError(
            f"No section for {owner!r}. Sections present: "
            + ", ".join(n for n, _ in index))
    pos, start = match

    last = focus_render._last_used_row(rows)
    end = index[pos + 1][1] if pos + 1 < len(index) else last + 1

    # Trim trailing blank rows (the spacer between sections) and blank columns.
    last_row, last_col = start, 0
    for r in range(start, min(end, len(rows))):
        for c, v in enumerate(rows[r].get("values", []) or []):
            if ((v or {}).get("formattedValue") or "").strip():
                last_row, last_col = max(last_row, r), max(last_col, c)
    return f"A{start + 1}:{_col_letter(last_col + 1)}{last_row + 1}"


def _fetch_pdf(base: str, token: str, rng: str, extra: str) -> bytes:
    """GET the export, honouring Google's throttling. The endpoint 429s on rapid
    requests; back off rather than losing the day's post to one bounce."""
    for attempt in range(6):
        r = requests.get(base + extra,
                         headers={"Authorization": f"Bearer {token}"}, timeout=90)
        if r.status_code in (429, 503):
            wait = 8 * (attempt + 1)
            try:
                wait = max(wait, int(r.headers.get("Retry-After", 0)))
            except (TypeError, ValueError):
                pass
            print(f"    …export {rng} throttled ({r.status_code}), "
                  f"retry {attempt + 1}/6 in {wait}s", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        # A HIDDEN tab exports as an empty 993-byte PDF with HTTP 200 — valid
        # PDF, no content, no error. Rasterising that posts a white rectangle
        # that looks like a good capture. [[shared.sheets_export]]
        return _sx.check_pdf(r.content, where=f"export {rng}")
    raise RuntimeError(f"export {rng}: throttled after retries")


def render_section(spreadsheet, tab_title: str, owner: str, out_path: Path,
                   *, scale: Optional[float] = None) -> Path:
    """Export one owner's section of `tab_title` to a trimmed PNG."""
    sheet = focus_render.fetch_grid(spreadsheet, tab_title)
    return _export_range(spreadsheet, tab_title, section_range(sheet, owner),
                         out_path, scale=scale)


def _export_range(spreadsheet, tab_title: str, rng: str, out_path: Path,
                  *, scale: Optional[float] = None) -> Path:
    """Render one A1 range of a tab to a trimmed PNG via the Sheets PDF export."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops

    scale = RENDER_SCALE if scale is None else scale
    ws = spreadsheet.worksheet(tab_title)

    base = (f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
            f"/export?format=pdf&gid={ws.id}&range={rng}"
            f"&gridlines=false&sheetnames=false&printtitle=false"
            f"&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05"
            f"&left_margin=0.05&right_margin=0.05")
    token = _access_token()

    # Fit-to-WIDTH landscape is crisp for these wide, short tables. If it
    # paginates, re-render fit-to-page so the board lands on ONE page instead of
    # being stitched with a seam through the middle of a row.
    dpi = round(200 * scale)
    doc = fitz.open(stream=_fetch_pdf(base, token, rng, "&portrait=false&fitw=true"),
                    filetype="pdf")
    if doc.page_count > 1:
        doc = fitz.open(stream=_fetch_pdf(base, token, rng, "&portrait=true&scale=4"),
                        filetype="pdf")
        dpi = round(320 * scale)

    def _trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        pad = 6
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    pages = [_trim(Image.open(io.BytesIO(pg.get_pixmap(dpi=dpi).tobytes("png")))
                   .convert("RGB")) for pg in doc]
    if len(pages) == 1:
        img = pages[0]
    else:
        w = max(p.width for p in pages)
        img = Image.new("RGB", (w, sum(p.height for p in pages)), (255, 255, 255))
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _bounds(rows, row_start: int, row_end: int) -> Optional[Tuple[int, int]]:
    """(last_row, last_col) with content in [row_start, row_end), or None."""
    last_row, last_col = -1, -1
    for r in range(row_start, min(row_end, len(rows))):
        for c, v in enumerate(rows[r].get("values", []) or []):
            if ((v or {}).get("formattedValue") or "").strip():
                last_row, last_col = max(last_row, r), max(last_col, c)
    return None if last_row < 0 else (last_row, last_col)


def group_ranges(sheet: dict, per: int = 3) -> List[str]:
    """A1 ranges covering the tab in groups of `per` owner sections.

    Mirrors focus_render.render_tab_grouped's split — group 0 keeps whatever
    sits above the first section, each later group starts at its own section
    anchor — so the captainship DMs keep their familiar "one image per 3
    owners" shape. Only the RENDERER changes.
    """
    rows = (sheet.get("data") or [{}])[0].get("rowData", []) or []
    last = focus_render._last_used_row(rows)
    if last < 0:
        raise RuntimeError("Tab appears empty — nothing to export.")
    index = section_index(sheet)
    if not index:
        b = _bounds(rows, 0, last + 1)
        return [f"A1:{_col_letter(b[1] + 1)}{b[0] + 1}"] if b else []

    out: List[str] = []
    n_groups = (len(index) + per - 1) // per
    for g in range(n_groups):
        row_start = 0 if g == 0 else index[g * per][1]
        nxt = (g + 1) * per
        row_end = index[nxt][1] if nxt < len(index) else last + 1
        b = _bounds(rows, row_start, row_end)
        if not b:
            continue
        out.append(f"A{row_start + 1}:{_col_letter(b[1] + 1)}{b[0] + 1}")
    return out


def render_tab_grouped(spreadsheet, tab_title: str, out_dir: Path,
                       prefix: str, per: int = 3,
                       *, scale: Optional[float] = None) -> List[Path]:
    """Exact-sheet replacement for focus_render.render_tab_grouped.

    Same contract — one PNG per `per` owner sections, returned top to bottom —
    but each image is exported by Google rather than redrawn, so Carlos's and
    Colten's DMs carry the sheet's real borders, wrapped headers and the black
    'Office Focus Report' band. The redraw had been dropping all three
    (Megan 2026-08-30: "they've been missed/messed up the whole time").
    """
    sheet = focus_render.fetch_grid(spreadsheet, tab_title)
    ranges = group_ranges(sheet, per=per)
    out_dir = Path(out_dir)
    return [_export_range(spreadsheet, tab_title, rng,
                          out_dir / f"{prefix}-{i}.png", scale=scale)
            for i, rng in enumerate(ranges, 1)]
