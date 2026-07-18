"""Rendering core for the program Sales Boards (B2B / Base / JE / BOX).

Produces the VA's two images per program off the `Sales Board` tab:
  (a) WEEKLY   — # / REP / Current Week / Last Wk, ranked by Current Week desc
  (b) HIGHROLLERS — # / REP / <yesterday's day>, only reps who sold that day,
      ranked by that day's count

WHY A TEMP TAB: the live tab carries a BASIC FILTER the VA toggles per campaign
and the PDF export honours it, so cropping raw rows returns whatever she last
filtered to. We duplicate the tab, clear the filter on the COPY, reshape it per
program, export, then delete it. The real tab is never touched.

WHY WE HIDE ROWS INSTEAD OF SLICING A RANGE: campaigns are NOT contiguous. The
sheet is sorted globally (24 interleaved runs observed 2026-07-18), so there is
no per-campaign row block to crop. For each program we hide every rep row that
isn't that campaign; the survivors collapse together and export as one clean
table directly above the totals block — exactly the VA's filtered view.
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import requests
from PIL import Image, ImageChops
from gspread.utils import rowcol_to_a1

from automations.recruiting_report.fill import _retry

NAME_COL = 2                 # col B — REP / totals labels
CAMPAIGN_COL = 12            # col L
CURRENT_WEEK_COL = 3         # col C
WEEKLY_LAST_COL = "D"        # crop weekly through Last Wk
DAY_HEADER_ROW = 4           # row carrying Monday..Sunday
FIRST_DAY_COL, LAST_DAY_COL = 5, 11    # cols E..K
TOTALS_TOP, TOTALS_BOTTOM = "AT&T (B2B)", "TOTAL"
PROGRAMS = ["B2B", "Base", "JE", "BOX"]


def cell(g, r, c):
    return g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else ""


def totals_range(g):
    top = bot = None
    for r in range(1, len(g) + 1):
        b = cell(g, r, NAME_COL).strip()
        if b == TOTALS_TOP and top is None:
            top = r
        if b == TOTALS_BOTTOM and top is not None:
            return top, r
    raise SystemExit("totals block (AT&T (B2B) … TOTAL) not found")


def rep_region(g, totals_top):
    """(first, last) row of the rep list — any row with a REP name and a known
    campaign, above the totals block. Order-independent."""
    rows = [r for r in range(1, totals_top)
            if cell(g, r, NAME_COL).strip() and cell(g, r, CAMPAIGN_COL).strip() in PROGRAMS]
    if not rows:
        raise SystemExit("no rep rows found")
    return min(rows), max(rows)


def day_column(g, dayname: str):
    for c in range(FIRST_DAY_COL, LAST_DAY_COL + 1):
        if cell(g, DAY_HEADER_ROW, c).strip().lower() == dayname.lower():
            return c
    return None


def as_int(s):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _dim(sheet_id, dim, idx, hidden):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": dim,
                  "startIndex": idx - 1, "endIndex": idx},
        "properties": {"hiddenByUser": hidden}, "fields": "hiddenByUser"}}


def set_rows_hidden(sh, sheet_id, rows, hidden: bool):
    if rows:
        sh.batch_update({"requests": [_dim(sheet_id, "ROWS", r, hidden) for r in rows]})


def set_cols_hidden(sh, sheet_id, cols, hidden: bool):
    if cols:
        sh.batch_update({"requests": [_dim(sheet_id, "COLUMNS", c, hidden) for c in cols]})


# A terminated rep gets "T" backfilled across their remaining days, so the LAST
# day of the week catches anyone terminated at any point. The VA's own basic
# filter does exactly this (col K hiddenValues ["T"]) — without it we showed 3
# terminated BOX reps she doesn't.
TERM_MARK = "T"
TERM_COL = LAST_DAY_COL          # Sunday


def is_terminated(g, r) -> bool:
    return cell(g, r, TERM_COL).strip().upper() == TERM_MARK


def sort_region(sh, sheet_id, first, last, specs, width):
    """Rank the rep region by an ordered list of (col, ascending?) specs — the VA
    sorts on more than one key, and ties land in a different order without them.
    Sorts the full row width so every column travels with its rep."""
    sh.batch_update({"requests": [{"sortRange": {
        "range": {"sheetId": sheet_id, "startRowIndex": first - 1, "endRowIndex": last,
                  "startColumnIndex": 0, "endColumnIndex": width},
        "sortSpecs": [{"dimensionIndex": c - 1,
                       "sortOrder": "ASCENDING" if asc else "DESCENDING"}
                      for c, asc in specs]}}]})


def renumber(tmp, first, last, keep):
    """Rewrite col A as a 1..N rank over the VISIBLE (kept) rows — the sheet
    stores each rep's ID there, so a filtered view would show skipped numbers."""
    col, rank = [], 0
    for r in range(first, last + 1):
        if r in keep:
            rank += 1
            col.append([rank])
        else:
            col.append([""])
    tmp.batch_update([{"range": f"A{first}:A{last}", "values": col}],
                     value_input_option="USER_ENTERED")


def export(sheet_id, gid, rng, token) -> Image.Image:
    base = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=pdf"
            f"&gid={gid}&range={rng}&gridlines=false&sheetnames=false&printtitle=false"
            f"&pagenumbers=false&fzr=false&top_margin=0.03&bottom_margin=0.03"
            f"&left_margin=0.03&right_margin=0.03&portrait=false&fitw=true")
    r = None
    for a in range(6):
        r = requests.get(base, headers={"Authorization": f"Bearer {token}"}, timeout=90)
        if r.status_code == 429:
            time.sleep(5 * (a + 1))
            continue
        r.raise_for_status()
        break
    import fitz
    pm = fitz.open(stream=r.content, filetype="pdf")[0].get_pixmap(dpi=200)
    im = Image.open(io.BytesIO(pm.tobytes("png"))).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bb = ImageChops.difference(im, bg).getbbox()
    if not bb:
        return im
    return im.crop((max(0, bb[0] - 4), max(0, bb[1] - 4),
                    min(im.width, bb[2] + 4), min(im.height, bb[3] + 4)))


def stitch(parts, gap=8):
    w = max(p.width for p in parts)
    h = sum(p.height for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for p in parts:
        out.paste(p, (0, y))
        y += p.height + gap
    return out


def render_all(sh, tmp, sheet_id, token, yday, out_dir: Path, programs=None):
    """Build both images for each program. Returns {program: {"a": path, "b": path}}."""
    programs = programs or PROGRAMS
    out_dir.mkdir(parents=True, exist_ok=True)
    gid, width = tmp.id, tmp.col_count
    g = _retry(tmp.get_all_values)
    ts, te = totals_range(g)
    first, last = rep_region(g, ts)
    result = {p: {} for p in programs}
    all_rows = list(range(first, last + 1))

    # ---------- (a) WEEKLY ----------
    # Current Week desc, then REP asc. Verified on her JE 7.17 (a): Joelle /
    # Juliett / Monica all sit on 9 and run alphabetically — Juliett would lead
    # if the day column were the tiebreak (she has 3 on Friday), so it isn't.
    sort_region(sh, gid, first, last,
                [(CURRENT_WEEK_COL, False), (NAME_COL, True)], width)
    g = _retry(tmp.get_all_values)
    header_a = export(sheet_id, gid, f"A2:{WEEKLY_LAST_COL}{DAY_HEADER_ROW}", token)
    for p in programs:
        keep = {r for r in all_rows if cell(g, r, CAMPAIGN_COL).strip() == p
                and cell(g, r, NAME_COL).strip() and not is_terminated(g, r)}
        if not keep:
            print(f"  ! {p}: no reps — skipped")
            continue
        hide = [r for r in all_rows if r not in keep]
        set_rows_hidden(sh, gid, hide, True)
        renumber(tmp, first, last, keep)
        # Bound the range to VISIBLE rows: if the last row of a range is hidden,
        # the export slides to the next visible one (it bled the totals block's
        # "AT&T (B2B)" row into the rep table).
        img = stitch([header_a,
                      export(sheet_id, gid,
                             f"A{min(keep)}:{WEEKLY_LAST_COL}{max(keep)}", token),
                      export(sheet_id, gid, f"A{ts}:{WEEKLY_LAST_COL}{te}", token)])
        path = out_dir / f"{p} Sales Board (a).png"
        img.save(path)
        result[p]["a"] = path
        print(f"  {p:5} (a) weekly      {len(keep):2} reps -> {path.name}")
        set_rows_hidden(sh, gid, hide, False)
        time.sleep(1.2)

    # ---------- (b) HIGHROLLERS: rank by yesterday's day column ----------
    dayname = yday.strftime("%A")
    dcol = day_column(g, dayname)
    if dcol is None:
        print(f"  ! no '{dayname}' column — skipping highrollers")
        return result
    # Her (b) ties break by Current Week desc (verified on JE 7.17: Joelle 9,
    # Monica 9, Dayanara 4 — all with 1 on Friday).
    sort_region(sh, gid, first, last,
                [(dcol, False), (CURRENT_WEEK_COL, False), (NAME_COL, True)], width)
    g = _retry(tmp.get_all_values)
    hide_cols = [c for c in range(CURRENT_WEEK_COL, LAST_DAY_COL + 1) if c != dcol]
    set_cols_hidden(sh, gid, hide_cols, True)
    # End on the DAY column (visible). Ending on LAST_DAY_COL — hidden whenever
    # the day isn't Sunday — made the export slide right into "Campaign".
    last_letter = rowcol_to_a1(1, dcol)[:-1]
    # Row 2's descriptor is a ~130-char formula in col C. C is hidden here, but
    # the text OVERFLOWS across the hidden columns and gets chopped at the first
    # visible one — that's the "eek Ending 7.19" fragment in the corner. A short
    # label fits inside C, so nothing bleeds through and the header reads clean.
    # (The sentence itself can't be shown: this view is 3 narrow columns wide,
    # and its content — week + day — is already in the gold cell and the column
    # header.)
    we_shown = cell(g, 2, 2).strip()
    tmp.batch_update([{"range": "C2",
                       "values": [[f"Week Ending {we_shown}  —  {dayname}"]]}],
                     value_input_option="USER_ENTERED")
    header_b = export(sheet_id, gid, f"A2:{last_letter}{DAY_HEADER_ROW}", token)
    for p in programs:
        keep = {r for r in all_rows if cell(g, r, CAMPAIGN_COL).strip() == p
                and not is_terminated(g, r)
                and (as_int(cell(g, r, dcol)) or 0) > 0}
        if not keep:
            print(f"  ! {p}: nobody sold on {dayname} — no highrollers image")
            continue
        hide = [r for r in all_rows if r not in keep]
        set_rows_hidden(sh, gid, hide, True)
        renumber(tmp, first, last, keep)
        img = stitch([header_b,
                      export(sheet_id, gid,
                             f"A{min(keep)}:{last_letter}{max(keep)}", token),
                      export(sheet_id, gid, f"A{ts}:{last_letter}{te}", token)])
        path = out_dir / f"{p} Sales Board (b).png"
        img.save(path)
        result[p]["b"] = path
        print(f"  {p:5} (b) highrollers {len(keep):2} reps ({dayname}) -> {path.name}")
        set_rows_hidden(sh, gid, hide, False)
        time.sleep(1.2)
    set_cols_hidden(sh, gid, hide_cols, False)
    return result
