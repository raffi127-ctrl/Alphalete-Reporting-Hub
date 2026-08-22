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
          highlight_last_row: bool = False,
          highlight_first_row: bool = False) -> Path:
    """Generic table → PNG. `name_col` (0-based) is left-aligned + bold.

    wrap_headers=False (default): every existing board unchanged — column
    width fits the one-line header.
    wrap_headers=True (Raf's Loom 2026-08-22, fiber Total Knocks): columns are
    sized to the DATA, and the header words wrap onto extra lines instead of
    stretching the box — "shorten up these boxes … make the number fit".
    highlight_last_row=True (Megan 2026-08-22, Weekly Knock Dispositions):
    the LAST row (a totals row) draws on the theme's header colour in bold
    white, so it reads apart from the rep rows. Default False = every
    existing board byte-identical."""
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

    img_h = PAD + TITLE_H + header_h + ROW_H * len(rows) + PAD
    img = Image.new("RGB", (banner_w + 2 * PAD, img_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.rectangle([PAD, PAD, PAD + banner_w, PAD + TITLE_H], fill=theme["title_bg"])
    d.text((PAD + CELL_PAD_X, PAD + (TITLE_H - title_size) // 2), title,
           font=f_title, fill=TITLE_FG)

    y, x = PAD + TITLE_H, PAD
    for ci in range(ncol):
        d.rectangle([x, y, x + col_w[ci], y + header_h], fill=theme["header_bg"])
        lines = head_lines[ci]
        block_h = head_lh * len(lines)
        ty = y + (header_h - block_h) // 2 + 1
        for ln in lines:
            # Center each header line in its cell (Megan 2026-08-22).
            tx = x + max((col_w[ci] - _text_w(d, ln, head_font)) // 2,
                         head_pad if wrap_headers else CELL_PAD_X)
            d.text((tx, ty), ln, font=head_font, fill=HEADER_FG)
            ty += head_lh
        x += col_w[ci]

    y += header_h
    for ri, r in enumerate(rows):
        is_total = ((highlight_last_row and ri == len(rows) - 1)
                    or (highlight_first_row and ri == 0))
        bg = (theme["header_bg"] if is_total
              else ROW_BG_A if ri % 2 == 0 else theme["stripe"])
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
                        rows: list[dict] | None = None,
                        title_suffix: str = "") -> Path:
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
    """
    if rows is not None:
        header, rows = _table_from_rows(rows)
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    # Raf's Loom 2026-08-22 — ONE combined fiber board: drop ID, pull Gaps +
    # Total Gaps in (in front of Last Knock) so the separate Time Gaps post
    # retires, alphabetical by rep, and wrapped headers so the boxes hug the
    # numbers instead of the header text.
    idx = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k and k not in idx:
            idx[k] = i
    missing = [c for c in COMBINED_KNOCKS_COLUMNS if _norm(c) not in idx]
    if missing:
        raise RuntimeError(f"Tab {tab!r} missing column(s) for Total Knocks: "
                           f"{missing}. Header: {header}")
    sel = [idx[_norm(c)] for c in COMBINED_KNOCKS_COLUMNS]
    sub = [[(r[i] if i < len(r) else "") for i in sel] for r in rows]
    rep_pos = COMBINED_KNOCKS_COLUMNS.index(COL_REP)
    tg_pos = COMBINED_KNOCKS_COLUMNS.index(COL_TOTAL_GAPS)
    sub.sort(key=lambda r: str(r[rep_pos]).strip().lower())

    # TOTAL footer (Megan 2026-08-22): every count column sums; the knock-time
    # cells show the office AVERAGE first/last knock (reps with a parsable
    # time only — same convention as the weekly dispositions board); Total
    # Gaps sums in minutes and shows as 'Xh Ym'.
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

    totals: list[str] = []
    for ci, c in enumerate(COMBINED_KNOCKS_COLUMNS):
        if c == COL_REP:
            totals.append("TOTAL")
        elif c in (COL_FIRST_KNOCK, COL_LAST_KNOCK):
            totals.append(_avg_time(ci))
        else:
            totals.append(str(sum(_int0(r[ci]) for r in sub)))

    for r in sub:
        r[tg_pos] = _fmt_hm(r[tg_pos])
    totals[tg_pos] = _fmt_hm(totals[tg_pos])
    # Office row at the TOP, right under the header (Raf 2026-08-22:
    # "averages of the whole office at the top").
    sub.insert(0, totals)
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    disp = [COMBINED_KNOCKS_DISPLAY.get(c, c) for c in COMBINED_KNOCKS_COLUMNS]
    return _draw(disp, sub,
                 f"TOTAL KNOCKS — {_office}{_title_date(target)}",
                 THEME_AMBER, out_dir / f"total_knocks_{target.isoformat()}.png",
                 name_col=0, wrap_headers=True, highlight_first_row=True)


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
                     title_suffix: str = "") -> Path:
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
                 f"TIME GAPS — {_office}{_title_date(target)}",
                 THEME_TEAL, out_dir / f"time_gaps_{target.isoformat()}.png")


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
                             title_suffix: str = "") -> Path:
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
                 f"TELEMAPPER KNOCKS — {_office}{_title_date(target)}",
                 THEME_AMBER,
                 out_dir / f"telemapper_knocks_{target.isoformat()}.png")


def render_wireless_total_knocks(target: dt.date, *, rows: list[dict],
                                 out_dir: Path = OUT_DIR_DEFAULT,
                                 title_suffix: str = "") -> Path:
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
                 f"TOTAL KNOCKS — {_office}{_title_date(target)}",
                 THEME_AMBER,
                 out_dir / f"total_knocks_{target.isoformat()}.png")


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
