"""Render each section of the daily post to a PNG, exactly as Jolie posts them.

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
  daily        -- full leaderboard, day-Apps columns, through Teams 'Alphaletes TOTALS'
  team         -- ONE per team (col CI): running Apps + last completed day expanded
  highrollers  -- only reps who produced yesterday, sorted by the day's Apps
  ranking      -- running block E-J expanded, sorted by APPS/INT/NL
"""
from __future__ import annotations

import datetime as dt
import io
import re
import time
from pathlib import Path
from typing import List, Tuple

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials

from automations.recruiting_report.fill import (
    open_by_key, _client, SCOPES, OAUTH_TOKEN_PATH,
)

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
TMP_TAB = "_auto_screenshot_tmp"
DAY_NAMES = {"MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"}


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
        m = re.search(r"sales board we\s*(\d+)\.(\d+)", w.title.lower())
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
    if containing:
        return sorted(containing)[-1][1]
    return sorted(parsed)[-1][1]        # fallback: newest week-ending


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


def _day_block(grid, day: dt.date) -> Tuple[int, int]:
    """(start,end) 0-based cols of `day`'s 7-metric block (Apps..Cx), by matching
    the day-of-month header (row 2) under a day-name header (row 1)."""
    dom = str(day.day)
    start = next((c for c in range(len(grid[1]))
                  if _cell(grid, 1, c).strip() == dom
                  and _cell(grid, 2, c).strip().lower() == "apps"
                  and _cell(grid, 0, c).strip() in DAY_NAMES), None)
    if start is None:
        raise RuntimeError(f"no day block for {day} (day-of-month {dom})")
    return start, start + 6


def last_completed_day(today: dt.date) -> dt.date:
    """The prior day -- what Jolie's morning post shows."""
    return today - dt.timedelta(days=1)


def _running_apps_col(grid) -> int:
    return 3            # D, first APPS under 'RUNNING WEEK TOTALS' (structurally fixed)


def _daily_show_cols(grid) -> set:
    """DP visible set (by header label): #, name, running-APPS, last-week-APPS, each
    day's Apps, the identity columns, and the Teams-table avg columns."""
    show = {0, 1, 2, 3}                                  # A, B, C, D(running APPS)
    # last-week APPS
    show.add(next(c for c in range(len(grid[0]))
                  if _cell(grid, 0, c).strip() == "LAST WEEK'S TOTALS"
                  and _cell(grid, 2, c).strip().upper() == "APPS"))
    # each day's Apps
    for c in range(len(grid[1])):
        if _cell(grid, 0, c).strip() in DAY_NAMES and _cell(grid, 2, c).strip().lower() == "apps":
            show.add(c)
    # identity columns by their row-1 header
    for lbl in ("Trainer", "Field Status", "Team", "Leadership Status", "Location"):
        show.add(next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == lbl))
    # Completed / ATTUID by their row-3 header
    for lbl in ("Completed", "ATTUID"):
        show.add(next(c for c in range(len(grid[0])) if _cell(grid, 2, c).strip() == lbl))
    # Teams-table avg columns (row-158-ish header band); by label so they survive moves
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


def _export_png(gid: int, rng: str, out_path: Path, token: str) -> Path:
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    base = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=pdf"
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
            return r.content
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

        # common filters: hide blank rep names
        filt_specs.append({"columnIndex": 2, "filterCriteria": {"hiddenValues": [""]}})

        if kind == "daily":
            show = _daily_show_cols(grid)
            right = col_letter(max(show))
            bottom = _label_row(grid, "Alphaletes TOTALS")
            export_rng = f"A1:{right}{bottom}"
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})

        elif kind == "team":
            d0, d1 = _day_block(grid, last_completed_day(today))
            show = {0, 1, 2, 3} | set(range(d0, d1 + 1))     # #, name, running APPS, day block
            export_rng = f"A1:{col_letter(d1)}{tot_row}"
            team_col = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Team")
            teams = sorted({_cell(grid, r, team_col).strip() for r in range(3, tot_row - 1)
                            if _cell(grid, r, 2).strip() and _cell(grid, r, team_col).strip()})
            hide = [""] + [t for t in teams if t != team]
            filt_specs.append({"columnIndex": team_col, "filterCriteria": {"hiddenValues": hide}})
            filt_specs.append({"columnIndex": d0, "filterCriteria": {"hiddenValues": ["F", "T"]}})
            subtotal_cols = [3] + list(range(d0, d1 + 1))

        elif kind == "highrollers":
            d0, d1 = _day_block(grid, last_completed_day(today))
            show = {0, 1, 2} | set(range(d0, d1 + 1))        # #, name, day block (no running APPS)
            export_rng = f"A1:{col_letter(d1)}{tot_row}"
            sort_col = d0                                    # sort by the day's Apps
            filt_specs.append({"columnIndex": d0, "filterCriteria": {
                "condition": {"type": "NUMBER_GREATER",
                              "values": [{"userEnteredValue": "0"}]}}})
            subtotal_cols = list(range(d0, d1 + 1))

        elif kind == "ranking":
            show = set(range(0, 10))                         # A..J (# name + running block)
            export_rng = f"A1:J{tot_row}"
            sort_col = next(c for c in range(3, 10)
                            if _cell(grid, 2, c).strip().upper() == spec["sort"].upper())
            filt_specs.append({"columnIndex": sun, "filterCriteria": {"hiddenValues": ["F", "T"]}})
        else:
            raise ValueError(f"unknown kind {kind}")

        reqs += _hide_cols(gid, show, ncols)
        reqs.append({"setBasicFilter": {"filter": {
            "range": {"sheetId": gid, "startRowIndex": 2, "endRowIndex": tot_row - 1,
                      "startColumnIndex": 1, "endColumnIndex": 104},
            "sortSpecs": [{"dimensionIndex": sort_col, "sortOrder": "DESCENDING"}],
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


def capture_all(sections, today: dt.date, out_dir: Path, only=None) -> List[Tuple[dict, Path]]:
    """Render every section (Team Sales fans out per team). Returns [(meta, png)] in
    post order; `meta` carries the caption title + emoji/react for slack_post."""
    ss = open_by_key(SHEET_ID)
    _sweep_temp(ss)                    # clear any orphan temp from a prior crashed run
    ws = find_week_tab(ss, last_completed_day(today))   # tab that CONTAINS yesterday
    grid = ws.get_all_values()
    token = _access_token()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for spec in sections:
        if only and spec["id"] not in only:
            continue
        if spec["kind"] == "team":
            for team in team_list(grid):
                meta = dict(spec, title=f"{team} {spec['title']}", team=team)
                png = _render(ss, ws, grid, spec, today, out_dir, token, team=team)
                out.append((meta, png))
        else:
            png = _render(ss, ws, grid, spec, today, out_dir, token)
            out.append((dict(spec), png))
    return out, grid, ws.title
