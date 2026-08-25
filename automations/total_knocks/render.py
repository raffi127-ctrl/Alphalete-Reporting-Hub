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
from automations.total_knocks.aggregate import (
    COL_HRS_KNOCKING,
    hours_between,
    knock_time_key as _knock_time_key,
)
from automations.total_knocks.fill import SHEET_ID, TAB_TEST, TAB_PROD, HEADER_ROW
from automations.total_knocks.pull import (
    COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
    COL_TT_BREAKS, COL_TT_SALES_TIME, COL_TT_SALES,
    COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
    COL_NO_ANSWER, COL_TALK_TO_NI, COL_PRES_NI, COL_SALE,
    COL_NOT_INTERESTED, COL_COME_BACK, COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
    SHEET_COLUMNS,
    _norm,
)

# ---- themes (title bar / header row / alternating stripe) ----
THEME_AMBER = {        # Total Knocks (matches the Hub card #B45309)
    "title_bg": (180, 83, 9),
    "header_bg": (60, 47, 36),
    "stripe": (248, 244, 239),
    # TOTAL row pops against the dark header + white rows (Megan 2026-08-22:
    # "more of a contrasting color") — the title bar's burnt orange.
    "total_bg": (180, 83, 9),
}
THEME_TEAL = {         # Time Gaps — distinct colour (🕐)
    "title_bg": (13, 110, 139),
    "header_bg": (15, 52, 67),
    "stripe": (234, 243, 246),
    "total_bg": (13, 110, 139),
}
TITLE_FG  = (255, 255, 255)
HEADER_FG = (255, 255, 255)
ROW_BG_A  = (255, 255, 255)
GRID      = (224, 214, 204)
TEXT      = (38, 34, 30)
NAME_FG   = (20, 18, 16)

# Total Knocks shows columns A–N (the first 14); Gaps / Total Gaps are excluded.
TOTAL_KNOCKS_NCOL = 14
# The COMBINED fiber Total Knocks board (Raf's Loom 2026-08-22): no ID, Gaps +
# Total Gaps folded in ahead of Last Knock — it replaces the separate Time
# Gaps post for fiber offices. Alphabetical by rep, headers wrapped tight.
COMBINED_KNOCKS_COLUMNS = [
    COL_REP, COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
    # First + Last Knock side by side (Raf 2026-08-22), gaps right after.
    COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
    COL_NO_ANSWER, COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE,
    COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
]
# Display-only header shortening on the combined board — the two Not
# Interested labels each carry a long word that alone held their columns
# open (Megan 2026-08-22). Data keys stay the full canonical names.
COMBINED_KNOCKS_DISPLAY = {
    COL_TALK_TO_NI: "Talk To - Not Int",
    COL_PRES_NI: "Pres - Not Int",
}
# Derived at render time (Raf 2026-08-23: "AVG Hrs knocking per day"):
# (last knock − first knock) − total gaps, the same formula his weekly
# dispositions board uses. Rep rows show that day's hours; the TOTAL rows
# show the office average. The column name and the formula live in
# `total_knocks.aggregate` (imported above) so a multi-day fold, which has to
# average the per-day figure rather than re-derive it, shares both.
# "Talk To's per Rep" (Raf 2026-08-25) sits right after the Total Talk To it
# divides. On THIS board it is filled on the summary rows only — the office
# TOTAL and any comparison office's line — because those are the rows that
# aggregate a roster; every other row is already one rep, where the per-rep
# number and Total Talk To are the same figure. It is the comparable one: Raf's
# office and Chan's carry different headcounts, so a raw total says as much
# about roster size as about the day. Same column, same name and same 1-decimal
# format as the DAILY KNOCKS SUMMARY board (captainship_drafts), because the
# two land in front of the same reader.
COL_TALK_TO_PER_REP = "Talk To's per Rep"


def _with_derived(cols: list) -> list:
    """The board's OUTPUT columns: the scraped ones plus the two we compute —
    Talk To's per Rep after Total Talk to, Avg. Hrs Knocking after Total Gaps."""
    out = list(cols)
    out.insert(out.index(COL_TOTAL_TALK_TO) + 1, COL_TALK_TO_PER_REP)
    out.insert(out.index(COL_TOTAL_GAPS) + 1, COL_HRS_KNOCKING)
    return out


COMBINED_KNOCKS_HEADERS = _with_derived(COMBINED_KNOCKS_COLUMNS)
# The cells this board computes rather than reads — blank on a rep row unless
# stated otherwise, so `_combined_sub` never looks for them in the scrape.
DERIVED_COLUMNS = (COL_TALK_TO_PER_REP, COL_HRS_KNOCKING)
# Time Gaps shows just these, in this order.
TIME_GAPS_COLUMNS = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                     COL_GAPS, COL_TOTAL_GAPS]
# TeleMapper Knocks (the gaps-only/NDS stand-in for Total Knocks): mirrors the
# ownerville Time Tracker table itself — Raf's reference screen (2026-08-22) —
# since a wireless office has no Disposition page to count knocks from.
TELEMAPPER_KNOCKS_COLUMNS = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                             COL_TT_BREAKS, COL_GAPS, COL_TOTAL_GAPS,
                             COL_TT_SALES_TIME, COL_TT_SALES]
# Wireless (NDS) Total Knocks: the house board's shape, with the wireless
# disposition set — one Not Interested bucket, no Talk-To split, no Sale.
WIRELESS_KNOCKS_COLUMNS = [COL_ID, COL_REP, COL_TOTAL_LEADS_KNOCKED,
                           COL_TOTAL_KNOCKS, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                           COL_NO_ANSWER, COL_NOT_INTERESTED, COL_COME_BACK,
                           COL_INACCESSIBLE, COL_DO_NOT_KNOCK]

# ---- layout ----
PAD        = 16
TITLE_H    = 52
HEADER_H   = 40
ROW_H      = 28
CELL_PAD_X = 10   # was 4 — more breathing room so text isn't cramped to the grid
MIN_COL_W  = 26
MAX_COL_W  = 640  # was 320 — the old cap truncated wide headers ("Presentation –
                  # Not Interested") and long rep names; widen so every cell fits
                  # its text (Megan 2026-08-06: "all cells fit to text").
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
    # A multi-day fold carries Avg. Hrs Knocking as DATA (averaged per knocking
    # day) instead of leaving the board to derive it from folded times — see
    # total_knocks.aggregate. Only then does the column join the header.
    if any(COL_HRS_KNOCKING in rec for rec in records):
        header.append(COL_HRS_KNOCKING)
    rows: list[list[str]] = []
    for rec in records:
        cells = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
                 for c in header]
        if any(c.strip() for c in cells):
            rows.append(cells)
    return header, rows


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text or "", font=font))


def _split_word(probe, word: str, fit_w: int, font) -> list[str]:
    """Hyphenate a single too-wide word into chunks that fit fit_w — the
    only way a long word ("Inaccessible") stops dictating its column width."""
    out: list[str] = []
    cur = ""
    for ch in word:
        if cur and _text_w(probe, cur + ch + "-", font) > fit_w:
            out.append(cur + "-")
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out or [word]


def _wrap_header(probe, text: str, fit_w: int, font) -> list[str]:
    """Wrap a header into lines no wider than fit_w; a word wider than fit_w
    hyphenates rather than widening the column."""
    words: list[str] = []
    for w in text.split():
        if _text_w(probe, w, font) > fit_w:
            words.extend(_split_word(probe, w, fit_w, font))
        else:
            words.append(w)
    lines: list[str] = []
    cur = ""
    for w in words:
        joined = w if (cur.endswith("-") or not cur) else f" {w}"
        cand = cur + joined
        if cur and _text_w(probe, cand, font) > fit_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw(header: list[str], rows: list[list[str]], title: str, theme: dict,
          out_path: Path, name_col: int = 1,
          wrap_headers: bool = False,
          highlight_last_row: "bool | int" = False,
          highlight_first_row: "bool | int" = False,
          repeat_header_before: int = 0,
          top_row_colors: "list | None" = None,
          total_row_bgs: "list | None" = None) -> Path:
    """Generic table → PNG. `name_col` (0-based) is left-aligned + bold.

    wrap_headers=False (default): every existing board unchanged — column
    width fits the one-line header.
    wrap_headers=True (Raf's Loom 2026-08-22, fiber Total Knocks): columns are
    sized to the DATA, and the header words wrap onto extra lines instead of
    stretching the box — "shorten up these boxes … make the number fit".
    highlight_last_row (Megan 2026-08-22, Weekly Knock Dispositions): the
    last N rows (totals rows) draw on the theme's header colour in bold
    white, so they read apart from the rep rows — True/1 = just the last
    row, an int = that many trailing rows (a host board carrying another
    office's comparison totals). Default False = every existing board
    byte-identical.
    repeat_header_before (Raf 2026-08-23, "add the heads to the bottom"):
    N > 0 re-draws the header band directly above the last N rows, so a
    long board's totals block is readable without scrolling to the top.
    The bottom band uses theme["repeat_header_bg"] when present (Megan
    2026-08-23: lighter purple) — else the header colour.
    total_row_bgs (Megan 2026-08-23, "make Chan's row teal"): per-row fills
    for the trailing highlighted rows, in order — e.g. [plum, teal] paints
    the host OFFICE TOTALS plum and the comparison row teal. None = the
    theme default for all. Default None/0 = every existing board
    byte-identical."""
    f_title = _font(26, bold=True)
    f_head  = _font(13, bold=True)
    f_cell  = _font(13)
    f_name  = _font(13, bold=True)
    # Wrapped headers draw smaller (11px, line height 14) — the header is a
    # label, the number is the data, so the label never dictates the box
    # (Megan 2026-08-22: "still too much extra space in these columns").
    f_head_w = _font(11, bold=True)
    head_font = f_head_w if wrap_headers else f_head
    head_lh = 14 if wrap_headers else 16
    head_pad = 4 if wrap_headers else CELL_PAD_X

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    ncol = len(header)
    col_w = []
    head_lines: list[list[str]] = []
    for ci in range(ncol):
        w_cells = 0
        cell_font = f_name if ci == name_col else f_cell  # names draw bold
        for r in rows:
            w_cells = max(w_cells,
                          _text_w(probe, r[ci] if ci < len(r) else "", cell_font))
        if wrap_headers:
            # Floor: widest cell — the DATA sets the box. A header word only a
            # little wider than the data widens the box to stay whole ("Gaps",
            # "Knocks"); a truly oversize word ("Inaccessible") hyphenates
            # instead of holding the column open (Megan 2026-08-22).
            fit = max(w_cells, MIN_COL_W)
            for wd in header[ci].split():
                ww = _text_w(probe, wd, head_font)
                if fit < ww <= int(fit * 1.8) + 8:
                    fit = ww
            lines = _wrap_header(probe, header[ci], fit, head_font)
            while len(lines) > 3:      # cap the stack — widen a touch instead
                fit += 6
                lines = _wrap_header(probe, header[ci], fit, head_font)
            w_head = max(_text_w(probe, ln, head_font) for ln in lines)
            head_lines.append(lines)
            # The header gets its own tighter padding, so a long label only
            # widens the box by what the label truly needs.
            col_w.append(min(MAX_COL_W,
                             max(w_cells + 2 * CELL_PAD_X,
                                 w_head + 2 * head_pad,
                                 MIN_COL_W)))
        else:
            w = max(_text_w(probe, header[ci], head_font), w_cells)
            head_lines.append([header[ci]])
            col_w.append(min(MAX_COL_W, max(MIN_COL_W, w + 2 * CELL_PAD_X)))

    n_head_lines = max(len(ls) for ls in head_lines) if head_lines else 1
    header_h = (HEADER_H if n_head_lines == 1
                else 12 + head_lh * n_head_lines)

    table_w = sum(col_w)

    # FIT THE TITLE. The banner is only as wide as the table, and the text was
    # drawn at a fixed 26px with no wrap — so a title longer than the table was
    # silently CLIPPED at the image edge. Harmless while every title was
    # 'TIME GAPS — August 17, 2026'; the moment an office name went in
    # ('TIME GAPS — SAHIL MULTANI — …', 6 narrow columns) the year fell off.
    # Shrink to the largest size that fits (floor 14, still clearly readable);
    # only if even 14 overflows does the canvas widen to hold it, so every
    # existing image whose title already fit is byte-identical.
    title_size = 26
    for size in (26, 24, 22, 20, 18, 16, 14):
        f_title = _font(size, bold=True)
        title_size = size
        if _text_w(probe, title, f_title) + 2 * CELL_PAD_X <= table_w:
            break
    banner_w = max(table_w,
                   _text_w(probe, title, f_title) + 2 * CELL_PAD_X)

    _rep_at = (len(rows) - repeat_header_before
               if 0 < repeat_header_before < len(rows) else -1)
    img_h = (PAD + TITLE_H + header_h + ROW_H * len(rows) + PAD
             + (header_h if _rep_at >= 0 else 0))
    img = Image.new("RGB", (banner_w + 2 * PAD, img_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.rectangle([PAD, PAD, PAD + banner_w, PAD + TITLE_H], fill=theme["title_bg"])
    d.text((PAD + CELL_PAD_X, PAD + (TITLE_H - title_size) // 2), title,
           font=f_title, fill=TITLE_FG)

    def _header_band(y0: int, band_bg=None) -> int:
        x0 = PAD
        for ci in range(ncol):
            d.rectangle([x0, y0, x0 + col_w[ci], y0 + header_h],
                        fill=band_bg or theme["header_bg"])
            lines = head_lines[ci]
            block_h = head_lh * len(lines)
            ty = y0 + (header_h - block_h) // 2 + 1
            for ln in lines:
                # Center each header line in its cell (Megan 2026-08-22).
                tx = x0 + max((col_w[ci] - _text_w(d, ln, head_font)) // 2,
                              head_pad if wrap_headers else CELL_PAD_X)
                d.text((tx, ty), ln, font=head_font, fill=HEADER_FG)
                ty += head_lh
            x0 += col_w[ci]
        return y0 + header_h

    y = _header_band(PAD + TITLE_H)
    _n_hl = int(highlight_last_row or 0)   # True==1; int N = last N rows
    for ri, r in enumerate(rows):
        if ri == _rep_at:
            # The bottom header band — lighter shade when the theme has one
            # (Megan 2026-08-23).
            y = _header_band(y, theme.get("repeat_header_bg"))
        # highlight_first_row mirrors highlight_last_row: True==1; int N =
        # the first N rows (a board carrying other offices' totals above its
        # own, Raf 2026-08-23).
        _n_top = int(highlight_first_row or 0)
        is_total = (_n_hl and ri >= len(rows) - _n_hl) or ri < _n_top
        bg = (theme.get("total_bg", theme["header_bg"]) if is_total
              else ROW_BG_A if ri % 2 == 0 else theme["stripe"])
        # Per-row override for the top block (another office's totals line
        # draws in its own colour — Megan 2026-08-23).
        if ri < _n_top and top_row_colors and ri < len(top_row_colors) \
                and top_row_colors[ri]:
            bg = top_row_colors[ri]
        # …and for the trailing block: total_row_bgs in order — e.g.
        # [plum, teal] = host OFFICE TOTALS plum, comparison row teal
        # (Megan 2026-08-23).
        _blk = ri - (len(rows) - _n_hl) if _n_hl else -1
        if (is_total and total_row_bgs and 0 <= _blk < len(total_row_bgs)
                and total_row_bgs[_blk]):
            bg = total_row_bgs[_blk]
        d.rectangle([PAD, y, PAD + table_w, y + ROW_H], fill=bg)
        x = PAD
        for ci in range(ncol):
            val = r[ci] if ci < len(r) else ""
            font = f_name if (ci == name_col or is_total) else f_cell
            fg = (HEADER_FG if is_total
                  else NAME_FG if ci == name_col else TEXT)
            if val.strip().isdigit() and ci != 0:    # center counts (not ID)
                tx = x + (col_w[ci] - _text_w(d, val, font)) // 2
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
    yy += header_h
    for ri in range(len(rows) + 1):
        if ri == _rep_at and ri:
            yy += header_h                 # jump the bottom header band
        d.line([PAD, yy, PAD + table_w, yy], fill=GRID, width=1)
        yy += ROW_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _title_date(target: dt.date) -> str:
    return f"{target.strftime('%B')} {target.day}, {target.year}"


def _title_span(target: dt.date, end: "dt.date | None" = None) -> str:
    """The board's date line: one day, or a range when `end` is a later day.

    'August 18–23, 2026' inside a month, 'August 30 – September 2, 2026'
    across one, both years spelled out across a year boundary. `end` None or
    equal to `target` returns EXACTLY what the single-day board always said —
    the range feature must be invisible to a one-day request."""
    if end is None or end == target:
        return _title_date(target)
    if (target.year, target.month) == (end.year, end.month):
        return f"{target.strftime('%B')} {target.day}–{end.day}, {end.year}"
    if target.year == end.year:
        return (f"{target.strftime('%B')} {target.day} – "
                f"{end.strftime('%B')} {end.day}, {end.year}")
    return f"{_title_date(target)} – {_title_date(end)}"


def _date_text(target: dt.date, end: "dt.date | None" = None,
               override: str = "") -> str:
    """The date as it appears in a board's title bar.

    `override` (default '') lets ONE caller print it its own way without
    changing every knocks board in the fleet — the 9 PM post wants a compact
    '8/25' where the morning boards keep 'August 25, 2026'. Empty means the
    house format, so every existing caller is untouched."""
    return override or _title_span(target, end)


def _file_span(target: dt.date, end: "dt.date | None" = None) -> str:
    """Filename stem for the span — unchanged for a single day, so nothing
    that globs for an existing board's name stops finding it."""
    if end is None or end == target:
        return target.isoformat()
    return f"{target.isoformat()}_{end.isoformat()}"


def render_total_knocks(target: dt.date, *, tab: str = TAB_PROD,
                        sheet_id: str = SHEET_ID,
                        out_dir: Path = OUT_DIR_DEFAULT,
                        rows: list[dict] | None = None,
                        title_suffix: str = "",
                        end: "dt.date | None" = None,
                        date_text: str = "",
                        title_prefix: str = "",
                        hide_columns: "tuple[str, ...]" = (),
                        extra_totals: "list[tuple[str, list[dict]]] | None" = None) -> Path:
    """THE fiber knocks board — combined per Raf's Loom (2026-08-22): every
    disposition count PLUS Gaps + Total Gaps (in front of Last Knock), no ID
    column, alphabetical by rep, wrapped headers so the boxes hug the numbers.
    Replaces the separate Time Gaps post for fiber offices. Amber theme.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them instead of reading the Sheet, so callers can
    render a fresh pull without writing a production tab.

    `title_suffix` (optional): office name added to the title —
    'TOTAL KNOCKS — SAHIL MULTANI — August 17, 2026'. Needed when SEVERAL
    offices' images land in the SAME Slack thread, so an image read on its own
    still says whose office it is. Default ('') keeps the original title.

    `end` (optional): the last day of a multi-day board, for the title and the
    filename. The ROWS must already be folded (total_knocks.aggregate) — this
    only labels them. None / same-as-target renders exactly as it always did.

    `hide_columns` (optional): columns to leave OFF this board. For a derived
    column that only carries a number on the TOTAL row — Talk To's per Rep is
    one: a rep row IS one rep, so per-rep there would just repeat Total Talk to
    — the cost of keeping it is a blank stripe down the whole board. Eve
    2026-08-25 asked for it off the Captainship Report's per-owner boards,
    where the same figure per ICD already sits on the DAILY KNOCKS SUMMARY
    right above. A PARAMETER, not a header edit, for the same reason as
    title_prefix: this renderer also draws the metrics threads, the intraday
    slots and /knocks, and Raf asked for that column — dropping it from the
    header would take it off his boards too. Default () = unchanged.

    `title_prefix` (optional): words in front of "TOTAL KNOCKS" — e.g.
    "DAILY " for the per-owner boards inside a Captainship Report (Eve
    2026-08-25). It is a PARAMETER rather than a new title because this one
    renderer draws the same board for the metrics threads, the intraday slots
    and the on-demand /knocks replies; renaming it in place would relabel all
    of them. Default "" keeps every existing board byte-identical.
    """
    if rows is not None:
        header, rows = _table_from_rows(rows)
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    sub = _combined_sub(header, rows, where=f"tab {tab!r}")
    totals = _combined_totals("TOTAL", sub)

    # Extra offices' totals rows ABOVE ours (Raf 2026-08-23: "add Chan's
    # totals above ours daily") — each is (office name, records keyed by
    # SHEET_COLUMNS); only their TOTAL line shows, not their reps.
    extra_rows: list[list[str]] = []
    for name, recs in (extra_totals or []):
        x_header, x_rows = _table_from_rows(recs)
        if not x_rows:
            continue
        x_sub = _combined_sub(x_header, x_rows, where=f"extra office {name!r}")
        extra_rows.append(_combined_totals(f"{name.upper()} TOTAL", x_sub))

    hrs_pos = COMBINED_KNOCKS_HEADERS.index(COL_HRS_KNOCKING)
    tg_pos = COMBINED_KNOCKS_HEADERS.index(COL_TOTAL_GAPS)
    for r in sub:
        r[tg_pos] = _fmt_hm(r[tg_pos])
        r[hrs_pos] = _fmt_hm(r[hrs_pos])
    for t in extra_rows + [totals]:
        t[tg_pos] = _fmt_hm(t[tg_pos])
        t[hrs_pos] = _fmt_hm(t[hrs_pos])
    # Office rows at the TOP, right under the header (Raf 2026-08-22). An
    # extra office's line draws teal so it can't be misread as ours
    # (Megan 2026-08-23).
    table = extra_rows + [totals] + sub
    _colors = ([THEME_TEAL["title_bg"]] * len(extra_rows)
               + [THEME_AMBER["total_bg"]])
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    disp = [COMBINED_KNOCKS_DISPLAY.get(c, c) for c in COMBINED_KNOCKS_HEADERS]
    if hide_columns:
        # Drop by NAME, then take the same positions out of every row — the
        # totals and comparison rows included, so nothing shifts under a header.
        keep = [i for i, c in enumerate(COMBINED_KNOCKS_HEADERS)
                if c not in hide_columns]
        disp = [disp[i] for i in keep]
        table = [[r[i] for i in keep] for r in table]
    return _draw(disp, table,
                 f"{title_prefix}TOTAL KNOCKS — {_office}"
                 f"{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"total_knocks_{_file_span(target, end)}.png",
                 name_col=0, wrap_headers=True,
                 highlight_first_row=1 + len(extra_rows),
                 top_row_colors=_colors)


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
                     rows: list[dict] | None = None,
                     title_suffix: str = "",
                     end: "dt.date | None" = None,
                     date_text: str = "") -> Path:
    """PNG 2 — ID, Rep, First/Last Knock, Gaps, Total Gaps (min), sorted by
    Total Gaps (min) desc, teal theme. Total Gaps is shown as 'Xh Ym' (like
    Ownerville); the Sheet column itself stays in plain minutes.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them instead of reading the Sheet (this function does
    its own Total-Gaps-desc sort, so no pre-sort is needed). Default (None)
    preserves the exact Sheet-reading behaviour.

    `title_suffix` (optional): office name added to the title, same as
    render_total_knocks — needed when several offices' images land in the SAME
    Slack thread. Default ('') keeps the original title.
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
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(list(TIME_GAPS_COLUMNS), sub,
                 f"TIME GAPS — {_office}{_date_text(target, end, date_text)}",
                 THEME_TEAL,
                 out_dir / f"time_gaps_{_file_span(target, end)}.png")


def _combined_sub(header: list[str], rows: list[list[str]],
                  where: str = "") -> list[list[str]]:
    """Select + order one office's rows into the combined-board shape:
    COMBINED_KNOCKS_HEADERS order (Hrs Knocking computed), alphabetical by
    rep. Gap/hour cells stay raw minutes — the caller formats them."""
    idx = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k and k not in idx:
            idx[k] = i
    missing = [c for c in COMBINED_KNOCKS_COLUMNS if _norm(c) not in idx]
    if missing:
        raise RuntimeError(f"{where or 'data'} missing column(s) for Total "
                           f"Knocks: {missing}. Header: {header}")
    src = {c: i for i, c in enumerate(COMBINED_KNOCKS_COLUMNS)}
    fk, lk, tg = src[COL_FIRST_KNOCK], src[COL_LAST_KNOCK], src[COL_TOTAL_GAPS]
    # Hrs Knocking is (last − first) − total gaps… UNLESS the caller already
    # computed it. A multi-day fold must AVERAGE the per-day figure; re-deriving
    # it from folded cells would subtract a week of gaps from one day's span and
    # quietly print a wrong number. See total_knocks.aggregate.
    pre = idx.get(_norm(COL_HRS_KNOCKING))
    sel = [idx[_norm(c)] for c in COMBINED_KNOCKS_COLUMNS]

    def _cell(r: list[str], i: int) -> str:
        return r[i] if i < len(r) else ""

    sub = []
    for r in rows:
        base = [_cell(r, i) for i in sel]
        if pre is None:
            hrs = hours_between(base[fk], base[lk], base[tg])
            hrs = "" if hrs is None else str(hrs)
        else:
            hrs = str(_cell(r, pre))
        # Talk To's per Rep is blank here on purpose: this row IS one rep, so
        # the number would only repeat Total Talk to. `_combined_totals` fills
        # it on the rows that actually aggregate a roster.
        derived = {COL_HRS_KNOCKING: hrs, COL_TALK_TO_PER_REP: ""}
        # Built whole, BEFORE the sort — assembling by header name keeps every
        # derived cell tied to its own rep no matter how the table is ordered.
        sub.append([derived[c] if c in derived else base[src[c]]
                    for c in COMBINED_KNOCKS_HEADERS])
    rep_pos = COMBINED_KNOCKS_HEADERS.index(COL_REP)
    sub.sort(key=lambda r: str(r[rep_pos]).strip().lower())
    return sub


def _combined_totals(label: str, sub: list[list[str]]) -> list[str]:
    """One office's TOTAL line for the combined board: counts sum, the knock
    times average (reps with a parsable time only), Total Gaps sums, Hrs
    Knocking averages, and Talk To's per Rep divides. Gap/hour cells stay raw
    minutes for the caller."""
    def _int0(v) -> int:
        v = str(v).strip()
        return int(v) if v.isdigit() else 0

    def _avg_time(pos: int) -> str:
        mins = [m for m in (_knock_time_key(str(r[pos])) for r in sub)
                if m < 24 * 60]
        if not mins:
            return ""
        m = round(sum(mins) / len(mins))
        h, mm = divmod(m, 60)
        return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"

    tt_at = COMBINED_KNOCKS_HEADERS.index(COL_TOTAL_TALK_TO)
    totals: list[str] = []
    for ci, c in enumerate(COMBINED_KNOCKS_HEADERS):
        if c == COL_REP:
            totals.append(label)
        elif c in (COL_FIRST_KNOCK, COL_LAST_KNOCK):
            totals.append(_avg_time(ci))
        elif c == COL_HRS_KNOCKING:
            vals = [_int0(r[ci]) for r in sub if str(r[ci]).strip() != ""]
            totals.append(str(round(sum(vals) / len(vals))) if vals else "")
        elif c == COL_TALK_TO_PER_REP:
            # Per rep who WORKED — ownerville's Disposition by Rep only lists
            # reps with activity, so an office isn't diluted by someone who was
            # off. Same denominator the DAILY KNOCKS SUMMARY board uses.
            talk = sum(_int0(r[tt_at]) for r in sub)
            totals.append(f"{talk / len(sub):.1f}" if sub else "0")
        else:
            totals.append(str(sum(_int0(r[ci]) for r in sub)))
    return totals


def _knock_time_key(v: str) -> int:
    """'2:31 PM' -> minutes since midnight for sorting; blank/unparsable last.
    strptime %I (not %-I) so it runs on Windows too."""
    v = (v or "").strip()
    try:
        t = dt.datetime.strptime(v, "%I:%M %p")
        return t.hour * 60 + t.minute
    except ValueError:
        return 24 * 60 + 1


def render_telemapper_knocks(target: dt.date, *, rows: list[dict],
                             out_dir: Path = OUT_DIR_DEFAULT,
                             title_suffix: str = "",
                             end: "dt.date | None" = None,
                             date_text: str = "") -> Path:
    """The gaps-only (NDS/wireless) office's stand-in for the Total Knocks
    board: the ownerville Time Tracker table itself, amber theme (it fills the
    Total Knocks slot in the thread). A wireless office has no Disposition
    page, so there are no knock COUNTS anywhere — what TeleMapper records for
    them is knock activity: first/last knock, breaks, gaps, sales time, sales
    (Raf's reference screenshot, 2026-08-22). Rows sorted First Knock asc,
    matching the live page; Total Gaps shown as 'Xh Ym'."""
    recs = sorted(rows, key=lambda r: _knock_time_key(str(r.get(COL_FIRST_KNOCK, ""))))
    table = []
    for rec in recs:
        row = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
               for c in TELEMAPPER_KNOCKS_COLUMNS]
        if any(c.strip() for c in row):
            table.append(row)
    if not table:
        raise RuntimeError("No Time Tracker rows to render.")
    # Blank the zero gap cells like the live page does, then 'Xh Ym' the rest.
    g_pos = TELEMAPPER_KNOCKS_COLUMNS.index(COL_GAPS)
    tg_pos = TELEMAPPER_KNOCKS_COLUMNS.index(COL_TOTAL_GAPS)
    for r in table:
        if r[g_pos].strip() == "0":
            r[g_pos] = ""
        r[tg_pos] = "" if r[tg_pos].strip() == "0" else _fmt_hm(r[tg_pos])
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(list(TELEMAPPER_KNOCKS_COLUMNS), table,
                 f"TELEMAPPER KNOCKS — {_office}{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"telemapper_knocks_{_file_span(target, end)}.png")


def render_wireless_total_knocks(target: dt.date, *, rows: list[dict],
                                 out_dir: Path = OUT_DIR_DEFAULT,
                                 title_suffix: str = "",
                                 end: "dt.date | None" = None,
                                 date_text: str = "") -> Path:
    """TOTAL KNOCKS for a WIRELESS (NDS) office — same amber board as the
    house one, but the wireless disposition column set (one Not Interested
    bucket, no Talk-To split, no Sale). Rows come from the wireless-shaped
    Disposition by Rep table (rashad_metrics.knocks_pull scrapes it when the
    house columns aren't there). Sorted First Knock asc like the house board."""
    recs = sorted(rows, key=lambda r: _knock_time_key(str(r.get(COL_FIRST_KNOCK, ""))))
    table = []
    for rec in recs:
        row = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
               for c in WIRELESS_KNOCKS_COLUMNS]
        if any(c.strip() for c in row):
            table.append(row)
    if not table:
        raise RuntimeError("No wireless disposition rows to render.")
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(list(WIRELESS_KNOCKS_COLUMNS), table,
                 f"TOTAL KNOCKS — {_office}{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"total_knocks_{_file_span(target, end)}.png")


# ---------------------------------------------------------------- shapes ---
# Ownerville hands back THREE row shapes and each gets a different board (Raf
# 2026-08-22, "telemapper knocks … should be on there for the NDS guys"). The
# test is which COLUMNS the scrape found, not which office asked — an office's
# campaign can change without anyone editing config.
SHAPE_HOUSE = "house"          # fiber: full disposition columns
SHAPE_WIRELESS = "wireless"    # NDS disposition shape: counts, no Talk-To split
SHAPE_GAPS_ONLY = "gaps_only"  # no disposition page at all: Time Tracker only


def knocks_shape(rows: "list[dict]") -> str:
    """Which of the three board shapes `rows` is.

    Reads the first record's KEYS — a gaps-only office has no Total Knocks key
    at all (not a blank value), because those rows come from the Time Tracker
    JSON rather than the Disposition table. Lived as two inline booleans in
    rashad_metrics.knocks_run until on-demand /knocks needed the same routing.
    """
    if not rows:
        raise ValueError("knocks_shape() needs at least one row")
    first = rows[0]
    if COL_TOTAL_KNOCKS not in first:
        return SHAPE_GAPS_ONLY
    return SHAPE_WIRELESS if COL_TALK_TO_NI not in first else SHAPE_HOUSE


_SHAPE_COLUMNS = {
    SHAPE_HOUSE: COMBINED_KNOCKS_HEADERS,
    SHAPE_WIRELESS: WIRELESS_KNOCKS_COLUMNS,
    SHAPE_GAPS_ONLY: TELEMAPPER_KNOCKS_COLUMNS,
}


def needs_time_gaps(shape: str) -> bool:
    """Does `shape`'s main board still need a separate Time Gaps image?

    Only when that board does NOT already show Gaps + Total Gaps. Asked of the
    column list rather than hardcoded per shape, so giving a board those
    columns is all it takes to retire its duplicate post.
    """
    cols = _SHAPE_COLUMNS.get(shape) or ()
    return not (COL_GAPS in cols and COL_TOTAL_GAPS in cols)


def render_knocks_boards(target: dt.date, *, rows: "list[dict]",
                         out_dir: Path = OUT_DIR_DEFAULT,
                         title_suffix: str = "",
                         end: "dt.date | None" = None,
                         date_text: str = "",
                         extra_totals=None) -> "tuple[list[Path], str]":
    """Every board this row shape deserves, in post order: ([paths], shape).

    Time Gaps rides along ONLY when the main board doesn't already carry Gaps
    + Total Gaps. That was Raf's rule for the fiber board (Loom 2026-08-22:
    the combined board absorbed the gap columns, so the separate Time Gaps
    post went away), and it is a property of the COLUMNS, not of the office —
    so it holds wherever it's true. The TeleMapper board carries both, so a
    gaps-only office gets ONE image too (Megan 2026-08-25: "his boards should
    be merged, that should have been universal"). The wireless disposition
    board genuinely lacks them, so that shape keeps its pair.

    `extra_totals` (a comparison office's TOTAL line) applies to the house
    board ONLY — the comparison office is fiber, so its totals have no column
    to sit under on an NDS board.

    `end` (optional): last day of a multi-day board. It only labels the title
    and filename — `rows` must already be folded by total_knocks.aggregate —
    and it reaches BOTH boards of an NDS pair, so a gaps-only office's Time
    Gaps image carries the same span as the one above it.
    """
    shape = knocks_shape(rows)
    if shape == SHAPE_GAPS_ONLY:
        first = render_telemapper_knocks(target, rows=rows, out_dir=out_dir,
                                         title_suffix=title_suffix, end=end,
                                         date_text=date_text)
    elif shape == SHAPE_WIRELESS:
        first = render_wireless_total_knocks(target, rows=rows,
                                             out_dir=out_dir,
                                             title_suffix=title_suffix,
                                             end=end, date_text=date_text)
    else:
        return ([render_total_knocks(target, rows=rows, out_dir=out_dir,
                                     title_suffix=title_suffix, end=end,
                                     date_text=date_text,
                                     extra_totals=extra_totals)], shape)
    if not needs_time_gaps(shape):
        return ([first], shape)
    gaps = render_time_gaps(target, rows=rows, out_dir=out_dir,
                            title_suffix=title_suffix, end=end,
                            date_text=date_text)
    return ([first, gaps], shape)


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
