"""Render each section of the daily post to a PNG.

This IS the morning post now: Jolie left the company (2026-08-13) and nobody
posts these by hand any more. The framing still matches what she used to send,
because that is what the team reads every morning.

Every image is a Google-Sheets PDF-export of the 'Sales Board WE m.d' tab, but the
tab's live filter/column-collapse drifts all day, so we NEVER shoot the live tab.
For each image we:

    1. duplicate the current-week tab to a hidden-bot throwaway copy,
    2. ENFORCE the canonical view on the copy (columns shown, sort, filters, a
       clean 1..N '#' counter, per-team/section subtotals) -- all by label, no
       hardcoded rows/cols, so template drift survives,
    3. PDF-export the copy -> PNG (PyMuPDF), trim margins,
    4. DELETE the copy (in a finally; also sweeps orphans from a crashed run).

The live sheet the team is using is never touched. Recipes per 'kind':
  daily        -- full leaderboard, day-Apps columns for days already played, through
                  the reps-summary band under TOTALS (Teams table has its own post)
  team_totals  -- the Teams table alone: CURRENT/LAST WEEK Total Units + per-day Apps
                  through 'Alphaletes TOTALS' (Raf 8/23 'All Teams Sales Board')
  team_totals_detail -- the same Teams table with the CURRENT WEEK group opened up
                  into its products (Total Units/INT/INT UP/DTV/NL/EN/CX), Eve 8/31
  field_status -- daily leaderboard, 1st-4th-week reps only, grouped by Field Status
  energy       -- daily leaderboard filtered to Campaign = Energy, ranked by Apps
  team         -- ONE per team: full running-week block + last-week Apps + identity thru
                  Leadership Status. Normal day opens up that day's block (+Roll Call);
                  Monday shows each day Mon-Sun Apps, nothing opened up
  highrollers  -- only reps who produced yesterday, sorted by the day's Apps
  zeros        -- escalating Zero Streak, one image per depth (see zeros_streak.py;
                  fanned out in capture_all, not rendered here)
  ranking      -- running block E-J expanded, sorted by APPS/INT/NL
  new_starts   -- the 'New Starts/Raf' roll-call table under the board: name /
                  Trainer / Location / Team + Monday..Saturday (Eve 8/31). Tue-Sun
                  only -- Monday's list isn't known until people show up
"""
from __future__ import annotations

import datetime as dt
import io
import re
import time
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials

from automations.shared import sheets_export as _sx
from automations.recruiting_report.fill import (
    open_by_key, _client, SCOPES, OAUTH_TOKEN_PATH,
)

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
TMP_TAB = "_auto_screenshot_tmp"
DAY_NAMES = {"MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"}
# the New Starts table spells its days out and stops at Saturday (Eve 8/31)
NEW_START_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
# The day-block columns the morning photo opens up, matched on the row-3 header.
# 'EN' and 'TK' are both here because the rename went tab by tab. The Talk-To
# trio is in because Rafael asked for it (2026-09-11: the new columns go in the
# screenshots, daily and weekly alike). An unknown header is still never
# photographed -- that is what keeps the next column from changing the post on
# its own.
DAY_PHOTO_HEADERS = ("apps", "int", "int up", "dtv", "nl", "en", "tk",
                     "total talk-to's", "% of tt's per knock", "avg app per tt",
                     "cx")

# Headers whose TOTALS cell must NEVER be rewritten as a SUM. `_subtotal_totals`
# turns the totals row into SUBTOTAL(109,...) so a filtered photo totals only the
# rows it shows -- right for counts, nonsense for a rate: summing
# "% of TT's per knock" down 60 reps reads 1,200%. These keep the board's own
# formula instead, which is a ratio and already says something true.
RATE_HEADERS = ("% of tt's per knock", "avg app per tt", "avg tt's per day",
                "avg tts per app", "avg total knocks per day")


# ---- small helpers -------------------------------------------------------

def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(grid, r, c):        # 0-based
    return grid[r][c] if r < len(grid) and c < len(grid[r]) else ""


def find_week_tab(ss, target: dt.date):
    """The 'Sales Board WE m.d' tab whose Mon-Sun week CONTAINS `target` (the last
    completed day). Tab is named by its week-ENDING Sunday (m.d), so the week runs
    (end-6 .. end). This makes MONDAY correct: yesterday=Sunday belongs to the just-
    finished week's tab, not a fresh new-week tab. Matched by pattern, never hardcoded.
    Falls back to the newest tab if none contains target (e.g. data-entry lag)."""
    parsed = []
    for w in ss.worksheets():
        # anchor at START so "Energy Sales Board WE 7.5" (a different team's tab)
        # doesn't match "Sales Board WE ..."
        m = re.match(r"sales board we\s*(\d+)\.(\d+)", w.title.strip().lower())
        if not m:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        end = None
        for yr in (target.year, target.year - 1, target.year + 1):   # pick the near year
            try:
                cand = dt.date(yr, mo, d)
            except ValueError:
                continue
            if end is None or abs((cand - target).days) < abs((end - target).days):
                end = cand
        if end:
            parsed.append((end, w))
    if not parsed:
        raise RuntimeError("no 'Sales Board WE m.d' tab found")
    containing = [(end, w) for end, w in parsed
                  if end - dt.timedelta(days=6) <= target <= end]
    # key on the date only -- never compare Worksheet objects (they're not orderable)
    if containing:
        return max(containing, key=lambda t: t[0])[1]
    return max(parsed, key=lambda t: t[0])[1]        # fallback: newest week-ending


def _totals_row(grid) -> int:
    """1-based row of the leaderboard 'TOTALS' row (col C label)."""
    return next(r for r in range(3, len(grid))
               if _cell(grid, r, 2).strip().upper() == "TOTALS") + 1


def _label_row(grid, needle) -> int:
    """1-based row whose col-C == needle (case-insensitive)."""
    return next(r for r in range(len(grid))
                if _cell(grid, r, 2).strip().lower() == needle.lower()) + 1


def _sun_apps_col(grid) -> int:
    """The Sunday (last day of week) Apps column -- terminated reps carry F/T here."""
    return next(c for c in range(len(grid[0]))
                if _cell(grid, 0, c).strip() == "SUN"
                and _cell(grid, 2, c).strip().lower() == "apps")


class DayCols(NamedTuple):
    """The columns of one day block, each found by its row-3 header."""
    apps: int                    # the day's Apps column -- sort + filter anchor
    metrics: List[int]           # what the photo opens up, in board order
    roll_call: Optional[int]     # the day's Roll Call, or None if the tab has none


def _day_span(grid, day: dt.date) -> Tuple[int, int]:
    """(start,end) 0-based cols of `day`'s WHOLE block: its Apps column through
    the column before the next day's banner (the last column, for Sunday)."""
    dom = str(day.day)
    start = next((c for c in range(len(grid[1]))
                  if _cell(grid, 1, c).strip() == dom
                  and _cell(grid, 2, c).strip().lower() == "apps"
                  and _cell(grid, 0, c).strip() in DAY_NAMES), None)
    if start is None:
        raise RuntimeError(f"no day block for {day} (day-of-month {dom})")
    end = next((c for c in range(start + 1, len(grid[0]))
                if _cell(grid, 0, c).strip() in DAY_NAMES), len(grid[0])) - 1
    return start, end


def _day_block(grid, day: dt.date) -> DayCols:
    """`day`'s columns, located BY HEADER -- never by counting across.

    WHY NOT `start + 6`. The block was `Apps Int Int Up DTV NL TK Cx Roll Call`
    until the Talk-To trio landed between TK and Cx and made it eleven wide.
    Six across then landed on 'Total Talk-To's', and 'Roll Call' was read off
    the column where '% of TT's per knock' now sits -- so the morning post
    silently dropped Cx AND the roll call. A header lookup survives the next
    column somebody inserts; an offset does not.

    The trio is NOT in the photo (see DAY_PHOTO_HEADERS): widening what goes out
    every morning is Rafael's call, not a side effect of a rename."""
    start, end = _day_span(grid, day)
    metrics = [c for c in range(start, end + 1)
               if _cell(grid, 2, c).strip().lower() in DAY_PHOTO_HEADERS]
    if not metrics:
        raise RuntimeError(f"day block for {day} has no recognisable metric "
                           f"header in row 3 (cols {start}..{end})")
    rc = next((c for c in range(start, end + 1)
               if _cell(grid, 2, c).strip().lower() == "roll call"), None)
    return DayCols(apps=start, metrics=metrics, roll_call=rc)


def last_completed_day(today: dt.date) -> dt.date:
    """The prior day -- what the morning post shows."""
    return today - dt.timedelta(days=1)


def _norm_name(s: str) -> str:
    """Rep name stripped of parenthetical suffixes ('(Wk 3)', '(NC)', nicknames
    like '(Shun)') + collapsed whitespace, lowercased. The week suffix INCREMENTS
    every week ('… (Wk 2)' -> '(Wk 3)'), so a raw name won't match the same rep
    across weekly tabs — normalize both sides before comparing. Reused by the Zero
    Streak renderer to match reps across prior-week tabs."""
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", s)).strip().lower()


def _running_apps_col(grid) -> int:
    return 3            # D, first APPS under 'RUNNING WEEK TOTALS' (structurally fixed)


def _allowed_day_doms(through: dt.date) -> set:
    """Day-of-month labels (row 2 of each day block) for Monday-of-week .. `through`.
    Raf 8/23: days that haven't happened yet carry no data — drop them from the
    boards instead of showing columns of 0.00s."""
    start = through - dt.timedelta(days=through.weekday())
    return {str((start + dt.timedelta(days=i)).day)
            for i in range((through - start).days + 1)}


def _day_apps_cols(grid, through: dt.date | None = None) -> set:
    """Every day block's Apps column; with `through`, only days that have already
    happened (matched on the row-2 day-of-month). If the dom match comes up empty
    (data-entry lag put us on a tab that doesn't contain `through`), fall back to
    ALL day columns — a full board beats a board with no days at all."""
    all_days = {c for c in range(len(grid[1]))
                if _cell(grid, 0, c).strip() in DAY_NAMES
                and _cell(grid, 2, c).strip().lower() == "apps"}
    if through is None:
        return all_days
    allowed = _allowed_day_doms(through)
    kept = {c for c in all_days if _cell(grid, 1, c).strip() in allowed}
    return kept or all_days


def _field_status_col(grid) -> int:
    return next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Field Status")


def _campaign_col(grid) -> int:
    """The Campaign column (Fiber / Energy / Fiber-Wireless). Found by LABEL, never
    position — Maud may move it (Raf 7/14). The board currently carries TWO columns
    titled 'Campaign'; tie-break on whichever is actually filled in (most non-blank
    rep rows), so if the duplicate is ever deleted the survivor just wins outright."""
    tot = _totals_row(grid)
    cands = [c for c in range(len(grid[0])) if _cell(grid, 0, c).strip().lower() == "campaign"]
    if not cands:
        raise RuntimeError("no 'Campaign' column on the Sales Board (renamed?)")
    return max(cands, key=lambda c: sum(1 for r in range(3, tot - 1)
                                        if _cell(grid, r, 2).strip() and _cell(grid, r, c).strip()))


def _is_wk5_plus(v: str) -> bool:
    """True if a Field Status value means 5th week or beyond (a 'veteran').
    Robust to minor label drift: '5th wk+', '5th Wk +', '5+' all match; the
    1st–4th-week and 'RT' values do not."""
    s = v.strip().lower()
    return s.startswith("5") or "+" in s


def _daily_show_cols(grid, team_avgs: bool = True, *,
                     through: dt.date | None = None, drop: tuple = ()) -> set:
    """DP visible set (by header label): #, name, running-APPS, last-week-APPS, each
    day's Apps, the identity columns, and (optionally) the Teams-table avg columns.

    `through` — only show day columns for days that have already happened (Raf 8/23).
    `drop`    — identity header labels to LEAVE OUT (Raf 8/23: 'Leadership Status'
                and 'Location' off the Daily + Entry Level boards)."""
    show = {0, 1, 2, 3}                                  # A, B, C, D(running APPS)
    # A header we hunt for may be absent (label drift, a sheet-layout edit). A
    # missing one must NOT crash the whole report — skip it (rendering without
    # that column beats a StopIteration that kills the post) and log it.
    def _col(pred, what):
        c = next((c for c in range(len(grid[0])) if pred(c)), None)
        if c is None:
            print("[alphalete_production] warn: column not found: %s" % what)
        return c

    # last-week APPS — the block-title column ("LAST WEEK'S TOTALS") IS that
    # block's Apps column, mirroring D under "RUNNING WEEK TOTALS". The 7/2026
    # sheet edit that renamed running Apps -> "Total Apps" left last-week's Apps
    # header BLANK, so an "== APPS" match silently dropped col K from the Daily
    # Production image. Anchor on the row-1 title (unique to this block's Apps
    # col) and accept APPS / Total Apps / blank in row 3.
    lw = _col(lambda c: _cell(grid, 0, c).strip().upper().startswith("LAST WEEK")
              and _cell(grid, 2, c).strip().upper() in ("APPS", "TOTAL APPS", ""),
              "LAST WEEK / APPS")
    if lw is not None:
        show.add(lw)
    # each day's Apps (only days that have happened, when `through` is given)
    show |= _day_apps_cols(grid, through)
    # identity columns by their row-1 header
    for lbl in ("Trainer", "Field Status", "Team", "Leadership Status", "Location"):
        if lbl in drop:
            continue
        c = _col(lambda c, _l=lbl: _cell(grid, 0, c).strip() == _l, lbl)
        if c is not None:
            show.add(c)
    try:
        camp = _campaign_col(grid)          # Fiber / Energy / Fiber-Wireless (Raf 7/14)
    except Exception as e:                   # noqa: BLE001 — missing col shouldn't crash
        print("[alphalete_production] warn: %s" % e)
        camp = None
    if camp is not None:
        show.add(camp)
    # Completed / ATTUID by their row-3 header
    for lbl in ("Completed", "ATTUID"):
        c = _col(lambda c, _l=lbl: _cell(grid, 2, c).strip() == _l, lbl)
        if c is not None:
            show.add(c)
    # Teams-table avg columns (row-158-ish header band); by label so they survive moves
    if team_avgs:
        for c in range(len(grid[0])):
            for r in range(150, min(175, len(grid))):
                if _cell(grid, r, c).strip().upper() in (
                        "TOTAL UNITS AVG", "NEW INT AVG",
                        "LW TOTAL UNITS AVG", "LW NEW INT AVG"):
                    show.add(c)
                    break
    return show


# ---- export (PDF -> PNG) -------------------------------------------------

def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def _export_png(gid: int, rng: str, out_path: Path, token: str,
                sheet_id: str = SHEET_ID) -> Path:
    """Range of one tab -> trimmed PNG, via the Sheets PDF export endpoint.

    `sheet_id` defaults to the Sales Board so every existing caller is unchanged;
    energy_crossref passes the webform workbook through it."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    base = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=pdf"
            f"&gid={gid}&range={rng}&gridlines=false&sheetnames=false"
            f"&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def fetch(extra):
        r = None
        for a in range(6):                 # export endpoint 429/500/503s transiently
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"}, timeout=90)
            if r.status_code in (429, 500, 503):
                time.sleep(4 * (a + 1))
                continue
            r.raise_for_status()
            # A hidden tab exports as an empty 993-byte PDF with HTTP 200.
            return _sx.check_pdf(r.content, where=f"export {rng}")
        raise RuntimeError(f"export {rng}: {r.status_code if r else '??'} after retries")

    dpi = 200
    doc = fitz.open(stream=fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:                 # tall block -> fit-to-page, one sheet
        doc = fitz.open(stream=fetch("&portrait=true&scale=4"), filetype="pdf")
        dpi = 320

    def trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        p = 6
        return im.crop((max(0, bb[0] - p), max(0, bb[1] - p),
                        min(im.width, bb[2] + p), min(im.height, bb[3] + p)))

    pages = [trim(Image.open(io.BytesIO(pg.get_pixmap(dpi=dpi).tobytes("png"))).convert("RGB"))
             for pg in doc]
    if len(pages) == 1:
        img = pages[0]
    else:
        w = max(p.width for p in pages)
        img = Image.new("RGB", (w, sum(p.height for p in pages)), (255, 255, 255))
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


# ---- copy-tab lifecycle --------------------------------------------------

def _sweep_temp(ss):
    """Delete any leftover temp tab(s) from a prior crashed run (orphan cleanup)."""
    for w in ss.worksheets():
        if w.title == TMP_TAB:
            try:
                ss.batch_update({"requests": [{"deleteSheet": {"sheetId": w.id}}]})
            except Exception:
                pass


def _delete_gid(ss, gid):
    """Delete one sheet by its exact id (used in finally -- never re-lists, so it
    can't be defeated by stale worksheet metadata)."""
    try:
        ss.batch_update({"requests": [{"deleteSheet": {"sheetId": gid}}]})
    except Exception:
        pass


def _duplicate(ss, source_ws) -> int:
    rep = ss.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": source_ws.id, "insertSheetIndex": 0,
        "newSheetName": TMP_TAB}}]})
    return rep["replies"][0]["duplicateSheet"]["properties"]["sheetId"]


def _filter_end(ncols: int, filt_specs: list, sorts: list) -> int:
    """endColumnIndex for setBasicFilter — wide enough to CONTAIN every column
    the filter sorts or filters on.

    This was the literal 104 from the first commit (2026-07-05), back when the
    board ended around column CZ. The Talk-To columns (3 per day x 7 days, plus
    the weekly block) pushed the identity columns right, and by 2026-09-12 the
    board was 221 columns wide with Field Status at 120 and Team at 122 — both
    OUTSIDE a filter that still claimed to end at 104.

    Sheets does not answer that with a 400. It answers `[500]: Internal error
    encountered`, which reads exactly like a transient blip: the section dropped
    at 04:05, the noon retry produced the identical 500 eight hours later, and
    nothing in the message named a column. An out-of-range *filterSpec* is
    tolerated (every other section filters the F/T column at 106 and renders
    fine) — it is the out-of-range SORT that kills the request, which is why
    this one section of eleven failed.

    Derived, never a literal: `ncols` is the same board width _hide_cols already
    works in, and the max() keeps the range honest if a spec ever references a
    column past the populated grid."""
    referenced = [s["columnIndex"] + 1 for s in filt_specs]
    referenced += [c + 1 for c, _ in sorts]
    return max([ncols] + referenced)


def _hide_cols(gid, show: set, ncols: int) -> list:
    """updateDimensionProperties requests: only `show` columns visible in [0,ncols)."""
    reqs = []
    run_hidden = None
    start = 0
    for c in range(ncols + 1):
        hidden = c < ncols and c not in show
        if run_hidden is None:
            run_hidden, start = hidden, c
        elif hidden != run_hidden:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": start, "endIndex": c},
                "properties": {"hiddenByUser": run_hidden}, "fields": "hiddenByUser"}})
            run_hidden, start = hidden, c
    return reqs


def _clean_number_col(ss, gid_ws, tot_row: int):
    """Replace the '#' counter (relative =B+1, breaks on re-sort) with a filter-safe
    visible-row counter -> clean 1..N with no skips (Megan 7/5, all images)."""
    gid_ws.batch_update(
        [{"range": f"B4:B{tot_row - 1}",
          "values": [[f"=SUBTOTAL(103,C$4:C{r})"] for r in range(4, tot_row)]}],
        value_input_option="USER_ENTERED")


def _running_block(grid) -> List[int]:
    """The RUNNING WEEK TOTALS columns, banner to banner.

    The block grew by five when the weekly Talk-To columns landed, so anything
    that spelled it out (the 'ranking' section used A..J) now cuts it off. Read
    it from the row-1 banners and the width stops mattering."""
    def _hdr1(label):
        return next((c for c in range(len(grid[0]))
                     if _cell(grid, 0, c).strip().upper() == label), None)
    rw = _hdr1("RUNNING WEEK TOTALS")
    lw = _hdr1("LAST WEEK'S TOTALS")
    if rw is None or lw is None or lw <= rw:
        return [3]                               # D -- the running Apps, as before
    return list(range(rw, lw))


def _summable(grid, cols) -> List[int]:
    """`cols` minus the rate/average columns -- see RATE_HEADERS."""
    return [c for c in cols
            if _cell(grid, 2, c).strip().lower() not in RATE_HEADERS]


def _subtotal_totals(ss, gid_ws, cols: List[int], tot_row: int):
    """Rewrite the TOTALS row for `cols` to SUBTOTAL(109,..) so it sums only the
    shown rows (per-team / per-section subtotal, ignoring X/F/T text)."""
    data = [{"range": f"{col_letter(c)}{tot_row}",
             "values": [[f"=SUBTOTAL(109,{col_letter(c)}4:{col_letter(c)}{tot_row - 1})"]]}
            for c in cols]
    gid_ws.batch_update(data, value_input_option="USER_ENTERED")


# ---- per-kind recipes ----------------------------------------------------

def _render(ss, source_ws, grid, spec, today, out_dir, token, team=None):
    """Duplicate -> enforce this section's view -> export PNG -> delete copy."""
    tot_row = _totals_row(grid)
    sun = _sun_apps_col(grid)
    ncols = max(len(grid[0]), 110)
    kind = spec["kind"]

    gid = _duplicate(ss, source_ws)
    try:
        tmp_ws = next(w for w in ss.worksheets() if w.title == TMP_TAB)
        reqs, filt_specs, sort_col, export_rng, subtotal_cols = [], [], 3, None, []
        sorts = None            # [(col, order), ...]; None -> [(sort_col, "DESCENDING")]

        # common filters: hide blank rep names
        filt_specs.append({"columnIndex": 2, "filterCriteria": {"hiddenValues": [""]}})

        if kind == "daily":
            # Raf 8/23: leaderboard only — days already played, no Leadership
            # Status / Location, and the Teams table moved to its OWN post
            # (kind='team_totals'). The reps-summary band right under TOTALS
            # ('Total Reps in the Field' .. '% of Reps on the Board') stays.
            show = _daily_show_cols(grid, team_avgs=False,
                                    through=last_completed_day(today),
                                    drop=("Leadership Status", "Location"))
            right = col_letter(max(show))
            bottom = max([r + 1 for r in range(tot_row - 1, min(tot_row + 20, len(grid)))
                          if _cell(grid, r, 2).strip().lower().startswith("% of reps")]
                         or [tot_row])
            export_rng = f"A1:{right}{bottom}"
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})

        elif kind == "team_totals":
            # Raf 8/23 (via Megan's screenshot): the Teams table that used to sit at
            # the bottom of Daily Production, as its OWN image — Teams / CURRENT WEEK
            # Total Units / LAST WEEK Total Units / per-day Apps, down through the
            # 'Alphaletes TOTALS' row. All by label; day columns trimmed to days
            # that have happened, same as the leaderboard.
            hdr = _label_row(grid, "Teams")
            bottom = _label_row(grid, "Alphaletes TOTALS")
            h0 = hdr - 1
            show = {2}                                   # C — team names
            for want in ("CURRENT WEEK", "LAST WEEK"):
                c = next((c for c in range(len(grid[h0]))
                          if _cell(grid, h0, c).strip().upper() == want), None)
                if c is None:
                    print("[alphalete_production] warn: Teams-table column not "
                          "found: %s" % want)
                else:
                    show.add(c)
            # the Teams table's MONDAY..SUNDAY Apps groups sit on the SAME columns
            # as the leaderboard's day blocks, so one helper serves both
            show |= _day_apps_cols(grid, last_completed_day(today))
            export_rng = f"C{hdr}:{col_letter(max(show))}{bottom}"

        elif kind == "team_totals_detail":
            # Eve 8/31: the SAME Teams table as 'team_totals', OPENED UP — the
            # CURRENT WEEK group expanded into its per-product columns (Total
            # Units / INT / INT UP / DTV / NL / EN / CX) instead of Total Units
            # alone, so the thread carries the product split next to the totals.
            # Posted immediately after 'All Teams Sales Board'.
            hdr = _label_row(grid, "Teams")
            bottom = _label_row(grid, "Alphaletes TOTALS")
            h0 = hdr - 1
            cw = next((c for c in range(len(grid[h0]))
                       if _cell(grid, h0, c).strip().upper() == "CURRENT WEEK"), None)
            if cw is None:
                raise RuntimeError("Teams table: no 'CURRENT WEEK' group header "
                                   f"on row {hdr} (renamed?)")
            # the group runs to the next group title on the same row (LAST WEEK) —
            # by header, so adding/removing a product column just works
            end = next((c for c in range(cw + 1, len(grid[h0]))
                        if _cell(grid, h0, c).strip()), len(grid[h0]))
            show = {2} | set(range(cw, end))             # C = team names + the block
            export_rng = f"C{hdr}:{col_letter(max(show))}{bottom}"

        elif kind == "new_starts":
            # Eve 8/31: the 'New Starts/Raf' roll-call table at the bottom of the
            # same tab — name across to Saturday, so the thread shows day by day
            # which new reps are still here and which came back Terminated. Only
            # renders Tue-Sun (pages.sections_for gates it; Monday's list of new
            # starts doesn't exist until people physically show up).
            hdr = _label_row(grid, "New Starts/Raf")     # orange title band
            lbl = _label_row(grid, "Classroom")          # column labels under it
            l0 = lbl - 1
            show = {2}                                   # C — the new start's name
            for want in ("Trainers", "Location", "Team"):
                c = next((c for c in range(len(grid[l0]))
                          if _cell(grid, l0, c).strip() == want), None)
                if c is None:
                    print("[alphalete_production] warn: New Starts column not "
                          "found: %s" % want)
                else:
                    show.add(c)
            days = [c for c in range(len(grid[l0]))
                    if _cell(grid, l0, c).strip() in NEW_START_DAYS]
            if not days:
                raise RuntimeError("New Starts table: no Monday..Saturday day "
                                   f"headers on row {lbl}")
            show |= set(days)                            # ends at Saturday (Eve 8/31)
            # last named row. A brand-new week's tab carries the header band with
            # NO rows under it until Monday's classroom actually shows up — say so
            # instead of dying on an empty max() (capture_all skips this section).
            named = [r for r in range(lbl + 1, len(grid) + 1)
                     if _cell(grid, r - 1, 2).strip()]
            if not named:
                raise RuntimeError("New Starts table is still empty on this tab "
                                   f"(no names under row {lbl}) — nobody has been "
                                   "added to the week's classroom yet")
            last = max(named)
            export_rng = f"C{hdr}:{col_letter(max(show))}{last}"

        elif kind == "team":
            # Raf 8/6 (from his screenshots, "what Eve sent"): the leader's own team, everything
            # from # across to Leadership Status. Full RUNNING WEEK TOTALS block + LAST WEEK'S
            # apps + Trainer / Field Status / Campaign / Team / Leadership Status. On a normal day
            # the current day is "opened up" (its 7-metric block + that day's Roll Call). On
            # MONDAY nothing is opened up — each day Mon–Sun shows just its Apps (whole week).
            def _hdr1(label):
                return next((c for c in range(len(grid[0]))
                             if _cell(grid, 0, c).strip() == label), None)
            lw = _hdr1("LAST WEEK'S TOTALS")
            run_block = _running_block(grid)
            show = {0, 1, 2} | set(run_block)               # #, name, full running-week block
            subtotal_cols = _summable(grid, run_block)
            if lw is not None:                               # LAST WEEK'S TOTALS -> APPS only
                show.add(lw)
                subtotal_cols.append(lw)
            if today.weekday() == 0:                         # MONDAY: each day's Apps, nothing opened
                day_apps = [c for c in range(len(grid[0]))
                            if _cell(grid, 0, c).strip() in DAY_NAMES
                            and _cell(grid, 2, c).strip().lower() == "apps"]
                show |= set(day_apps)
                subtotal_cols += day_apps
                filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})
            else:                                            # normal day: this day opened up + Roll Call
                dc = _day_block(grid, last_completed_day(today))
                show |= set(dc.metrics)
                subtotal_cols += _summable(grid, dc.metrics)
                if dc.roll_call is not None:                 # by header, not "the column after Cx"
                    show.add(dc.roll_call)
                filt_specs.append({"columnIndex": dc.apps, "filterCriteria": {"hiddenValues": ["F", "T"]}})
            # identity columns through Leadership Status (Trainer / Field Status / Team / Leadership)
            for lbl in ("Trainer", "Field Status", "Team", "Leadership Status"):
                c = _hdr1(lbl)
                if c is not None:
                    show.add(c)
            try:
                show.add(_campaign_col(grid))                # Fiber / Energy / Fiber-Wireless (by label)
            except Exception as e:                           # noqa: BLE001 — missing col shouldn't crash
                print("[alphalete_production] warn: %s" % e)
            team_col = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Team")
            teams = sorted({_cell(grid, r, team_col).strip() for r in range(3, tot_row - 1)
                            if _cell(grid, r, 2).strip() and _cell(grid, r, team_col).strip()})
            hide = [""] + [t for t in teams if t != team]
            filt_specs.append({"columnIndex": team_col, "filterCriteria": {"hiddenValues": hide}})
            export_rng = f"A1:{col_letter(max(show))}{tot_row}"

        elif kind == "highrollers":
            dc = _day_block(grid, last_completed_day(today))
            show = {0, 1, 2} | set(dc.metrics)               # #, name, day block (no running APPS)
            export_rng = f"A1:{col_letter(max(dc.metrics))}{tot_row}"
            sort_col = dc.apps                               # sort by the day's Apps
            filt_specs.append({"columnIndex": dc.apps, "filterCriteria": {
                "condition": {"type": "NUMBER_GREATER",
                              "values": [{"userEnteredValue": "0"}]}}})
            subtotal_cols = _summable(grid, dc.metrics)

        elif kind == "ranking":
            run_block = _running_block(grid)
            show = {0, 1, 2} | set(run_block)                # #, name, running block
            export_rng = f"A1:{col_letter(max(show))}{tot_row}"
            # Running-block metric header, matched drift-tolerantly. Maud renamed the
            # running Apps header "APPS" -> "Total Apps" (7/2026); an exact match then
            # StopIterationed and took down the WHOLE post. Accept the "Total " prefix,
            # and fall back to the known running-Apps column (D=3) rather than crash.
            want = spec["sort"].strip().upper()
            def _is_rank_hdr(c, _w=want):
                h = _cell(grid, 2, c).strip().upper()
                return h == _w or h == "TOTAL " + _w
            sort_col = next((c for c in run_block if _is_rank_hdr(c)),
                            run_block[0] if want in ("APPS", "TOTAL APPS") else None)
            if sort_col is None:
                raise RuntimeError(
                    f"ranking sort header {spec['sort']!r} not found in the running "
                    f"block {col_letter(run_block[0])}:{col_letter(run_block[-1])} "
                    f"(row-3 headers: {[_cell(grid, 2, c).strip() for c in run_block]})")
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})

        elif kind == "field_status":
            # daily leaderboard, first-4-weeks only, organized by tenure (Raf 7/10):
            # same columns as 'daily' minus the Teams-avg block, drop '5th wk+' reps,
            # sort by Field Status then running APPS.
            show = _daily_show_cols(grid, team_avgs=False,
                                    through=last_completed_day(today),
                                    drop=("Leadership Status", "Location"))
            right = col_letter(max(show))
            export_rng = f"A1:{right}{tot_row}"
            fs_col = _field_status_col(grid)
            fs_vals = {_cell(grid, r, fs_col).strip() for r in range(3, tot_row - 1)
                       if _cell(grid, r, 2).strip()}
            # entry-level 1st–4th-week board: drop veterans ('5th wk+') AND 'RT'
            hide_fs = [""] + [v for v in fs_vals
                              if _is_wk5_plus(v) or v.strip().upper() == "RT"]
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})
            filt_specs.append({"columnIndex": fs_col, "filterCriteria": {"hiddenValues": hide_fs}})
            el_team = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Team")
            sorts = [(el_team, "ASCENDING"), (3, "DESCENDING")]   # group by team, top Apps first (Raf 7/14)
            subtotal_cols = [c for c in show if _cell(grid, 2, c).strip().lower() == "apps"]

        elif kind == "energy":
            # Raf 7/14: the daily leaderboard filtered to Campaign = Energy, ranked by
            # running-week Apps high -> low. Campaign found by label (Maud may move it).
            show = _daily_show_cols(grid, team_avgs=False)
            right = col_letter(max(show))
            export_rng = f"A1:{right}{tot_row}"
            camp_col = _campaign_col(grid)
            camp_vals = {_cell(grid, r, camp_col).strip() for r in range(3, tot_row - 1)
                         if _cell(grid, r, 2).strip()}
            # keep ONLY Energy — hide every other campaign (incl. blank / Fiber-Wireless)
            hide_camp = sorted({v for v in camp_vals if v.strip().lower() != "energy"} | {""})
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})
            filt_specs.append({"columnIndex": camp_col, "filterCriteria": {"hiddenValues": hide_camp}})
            sorts = [(3, "DESCENDING")]           # rank by running-week APPS, high -> low
            subtotal_cols = [c for c in show if _cell(grid, 2, c).strip().lower() == "apps"]

        else:
            raise ValueError(f"unknown kind {kind}")

        if sorts is None:
            sorts = [(sort_col, "DESCENDING")]
        reqs += _hide_cols(gid, show, ncols)
        reqs.append({"setBasicFilter": {"filter": {
            "range": {"sheetId": gid, "startRowIndex": 2, "endRowIndex": tot_row - 1,
                      "startColumnIndex": 1,
                      "endColumnIndex": _filter_end(ncols, filt_specs, sorts)},
            "sortSpecs": [{"dimensionIndex": c, "sortOrder": o} for c, o in sorts],
            "filterSpecs": filt_specs}}})
        ss.batch_update({"requests": reqs})
        time.sleep(1.0)

        _clean_number_col(ss, tmp_ws, tot_row)
        if subtotal_cols:
            _subtotal_totals(ss, tmp_ws, subtotal_cols, tot_row)
        time.sleep(1.0)

        name = spec["id"] + (f"_{team}" if team else "")
        name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
        return _export_png(gid, export_rng, out_dir / f"{name}.png", token)
    finally:
        _delete_gid(ss, gid)


def team_list(grid) -> List[str]:
    team_col = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Team")
    tot_row = _totals_row(grid)
    return sorted({_cell(grid, r, team_col).strip() for r in range(3, tot_row - 1)
                   if _cell(grid, r, 2).strip() and _cell(grid, r, team_col).strip()})


def capture_all(sections, today: dt.date, out_dir: Path, only=None,
                failures=None) -> List[Tuple[dict, Path]]:
    """Render every section (Team Sales fans out per team). Returns [(meta, png)] in
    post order; `meta` carries the caption title + emoji/react for slack_post.

    `failures` -- pass a list to be told WHICH sections were skipped: it gets
    (section_id, reason) appended for each. A skipped section used to be visible
    only in the log, so the thread went out short and silent (Eve 8/31, on the
    New Starts table that isn't filled in until mid-morning). run.py turns a
    non-empty list into the #claudecorrections alert. Optional, so every existing
    caller (energy_crossref) is unchanged."""
    ss = open_by_key(SHEET_ID)
    _sweep_temp(ss)                    # clear any orphan temp from a prior crashed run
    ws = find_week_tab(ss, last_completed_day(today))   # tab that CONTAINS yesterday
    grid = ws.get_all_values()
    token = _access_token()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    failed = []
    for spec in sections:
        if only and spec["id"] not in only:
            continue
        # One section hitting label drift must NOT zero the whole post (it did on
        # 7/25 when "APPS"->"Total Apps" StopIterationed rank_apps). Render each
        # independently; log + skip any that fail so the rest still go out.
        try:
            if spec["kind"] == "team":
                for team in team_list(grid):
                    meta = dict(spec, title=f"{team} {spec['title']}", team=team)
                    png = _render(ss, ws, grid, spec, today, out_dir, token, team=team)
                    out.append((meta, png))
            elif spec["kind"] == "zeros":
                # Escalating Zero Streak: one image per depth (1 Day / 2 Days / …),
                # walked across prior-week tabs. Fans out like Team Sales.
                from automations.alphalete_production import zeros_streak
                out.extend(zeros_streak.render_streaks(
                    ss, ws, grid, spec, today, out_dir, token))
            else:
                png = _render(ss, ws, grid, spec, today, out_dir, token)
                out.append((dict(spec), png))
        except Exception as e:              # noqa: BLE001 — one bad section != dead post
            failed.append((spec["id"], f"{type(e).__name__}: {e}"))
            print(f"[alphalete_production] SECTION FAILED, skipping {spec['id']}: "
                  f"{type(e).__name__}: {str(e)[:200]}", flush=True)
    if failed:
        print("[alphalete_production] %d/%d section(s) failed: %s"
              % (len(failed), len(sections),
                 ", ".join(i for i, _ in failed)), flush=True)
    if failures is not None:
        failures.extend(failed)
    return out, grid, ws.title
