"""Locate the Sales Board ranges for the Captainship drafts BY LABEL.

Two sections come off the 'Alphalete ORG Sales Board' tab (the tab
the daily org_sales_board fill keeps current — same layout as the real tab):

  * PRODUCT SUMMARY — one block per captain, anchored on a col-B team header
    ("Raf's Captainship Team", "Wayne's Captain Team", "KHALIL'S CAPTAIN
    TEAM", …). Fiber + Rafael carry a second "ALL UNITS PERFORMANCE"
    sub-block that sits contiguous inside the same span, so one screenshot of
    the whole span shows both the New-Internet and All-Units tables.
  * CAPTAINSHIP UNITS — the "this week vs last week" delta charts further down
    (from ~row 1673). Each is anchored on a header row where col C reads
    "Total for week" and col B is "<Captain> Captainship". Fiber + Rafael get
    a NEW INTERNET UNITS chart and an ALL UNITS chart; B2B/NDS get one.

NOTHING here is a hardcoded row/col index — every block is found by its label
(and every day column by its day-name header), because the template moves.
Row-group expansion + the day-column math live here; the actual pixels are
real browser screenshots (see sheet_shot.py).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill as _rf

# Org Sales Board workbook. We screenshot the 'Copy of' tab: it is the sandbox
# tab the daily org_sales_board fill writes (freshest automated numbers) and
# the tab the spec names for the fiber/NDS/B2B sections. [[project_org-captainship-workbook-moved]]
SALES_BOARD_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
from automations.org_sales_board.tabs import BOARD_TAB

SALES_BOARD_TAB = BOARD_TAB

# How many columns the Product Summary block spans (A..L) — the true right edge
# of every table in it: the daily blocks end at "PREVIOUS WEEK'S TOTALS" (L) and
# the CAPTAIN TEAM historical ends at its 10th week column (L). Anything at M or
# beyond is older history that is NOT part of this report (Eve, 2026-07-28).
# The vertical weekly-historical detail lives in COLLAPSED ROW GROUPS inside the
# range (expanded for the screenshot).
#
# This was "K" until 2026-07-28, which cut the daily blocks' last column — but
# nobody saw that, because a browser selection is EXPANDED to cover any merged
# cell it touches, so the shot silently came back at whatever the widest merge
# in the span reached (Rafael L, Chan M). Hence grid_span() below: the shot's
# clip is measured from the sheet's own geometry, never from the selection.
PS_END_COL = "L"

# The name-token we look for inside a captain's block header, per captain key.
# Header text varies ("Raf's Captainship Team" / "Wayne's Captain Team" /
# "KHALIL'S CAPTAIN TEAM"), but the captain token is always present.
CAPTAIN_TOKEN = {
    "rafael": "raf", "wayne": "wayne", "starr": "starr", "chan": "chan",
    "tony": "tony", "sahil": "sahil", "carlos": "carlos", "eveliz": "eveliz",
    "luis": "luis", "khalil": "khalil", "colten": "colten", "jairo": "jairo",
    # 2026-08-18: Atef split off Carlos'. A captain MISSING here does not just
    # lose their own section — discover_blocks() walks the sheet top to bottom
    # and ends each span at the next RECOGNISED header, so the block above
    # silently swallows the unknown one. Atef's box sits under Luis', and Luis'
    # email came out carrying Atef's tables. Same failure the Khalil/Sahil note
    # below describes.
    "atef": "atef",
}

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")
_TOTAL_FOR_WEEK = "total for week"


@lru_cache(maxsize=1)
def _open_ws():
    """The Sales Board worksheet, opened ONCE per process.

    Cached because opening it is not free: open_by_key fetches the workbook
    metadata and .worksheet() the tab list, so every uncached call was two API
    reads before the real one. A 12-captain build called this ~250 times."""
    return _rf._client().open_by_key(SALES_BOARD_ID).worksheet(SALES_BOARD_TAB)


def _norm(s: str) -> str:
    return (s or "").strip()


@dataclass(frozen=True)
class UnitsBlock:
    label: str          # "NEW INTERNET UNITS" | "ALL UNITS" | "ALL UNITS"
    header_row: int     # 1-based row with the day-name headers
    start_row: int      # first row to screenshot (header)
    end_row: int        # last row to screenshot (inclusive)


@dataclass(frozen=True)
class CaptainBlocks:
    ps_start: int
    ps_end: int
    units: List[UnitsBlock]


@lru_cache(maxsize=1)
def _values() -> List[List[str]]:
    """All cell values of the Sales Board tab, fetched once per process.

    The docstring said "once per process" from the start; the cache that made
    it true was missing. Uncached, a 12-captain build re-read this ~2000-row
    tab about 25 times (every captain: once here, once inside ps_shot_plan,
    once per prior_day_columns) — with the two opens above, roughly 20 API
    reads per captain. Google's Sheets read quota is 60/min/user, so a build
    reliably tripped it around the THIRD captain and every captain after that
    lost §1 to a 429 while the first two looked perfect. The row layout is
    already frozen for the process by discover_blocks' own cache, so holding
    the values beside it changes nothing about what a run sees."""
    return _open_ws().get_all_values()


# "captai" (not "captain") tolerates the sheet's typo'd headers, e.g.
# "Starr's Captaiship" (missing the 'n') — still excludes "RAF SPECIAL
# TEAM" / "TRANG'S ORG" which carry no captai* word.
def _is_ps_header(b: str, token: str) -> bool:
    b = b.lower()
    return token in b and "captai" in b and "team" in b


# The banner strip that sits ABOVE a team header on the fiber/Rafael blocks:
# "📶 NEW INTERNET PERFORMANCE" over "Raf's Captainship Team" (and, mid-block,
# "🛜ALL UNITS PERFORMANCE" over the second sub-block). It carries no captain
# token, so _is_ps_header can't anchor on it and the span started one row too
# low — the emailed §1 opened straight on the team name with the band cut off
# (Eve, 2026-08-03). The second banner was always fine: it sits INSIDE the span.
# B2B/NDS blocks have no banner row, so this is a no-op for them.
_BANNER_RE = re.compile(r"(?i)\bPERFORMANCE\b")


def _banner_start(cell, header_row: int, limit: int = 2) -> int:
    """`header_row` walked up over the PERFORMANCE banner rows above it.

    Bounded (`limit`) and text-driven: it only climbs over rows that actually
    say PERFORMANCE in col B (col A fallback, same as the header lookup), so a
    block without a banner keeps its own header row and no block can eat the
    tail of the one above it. A row that is itself a captain header stops the
    walk, so two adjacent blocks can never merge."""
    r = header_row
    for _ in range(limit):
        prev = r - 1
        if prev < 1:
            break
        text = cell(prev, 2) or cell(prev, 1)
        if not text or not _BANNER_RE.search(text):
            break
        if any(_is_ps_header(text, t) for t in CAPTAIN_TOKEN.values()):
            break
        r = prev
    return r


def _is_units_header(b: str, c: str, token: str) -> bool:
    b = b.lower()
    return (c.strip().lower() == _TOTAL_FOR_WEEK and token in b
            and "captai" in b)


def _trim_trailing_blank(vals, start: int, end: int, ncols: int) -> int:
    """Pull `end` (1-based, inclusive) back past rows that are blank in A..K."""
    while end > start:
        row = vals[end - 1] if end - 1 < len(vals) else []
        if any(_norm(row[j]) for j in range(min(ncols, len(row)))):
            break
        end -= 1
    return end


@lru_cache(maxsize=1)
def discover_blocks() -> Dict[str, CaptainBlocks]:
    """Map every captain key -> its Product Summary span + Units chart(s),
    all located by label on the live sheet."""
    vals = _values()
    n = len(vals)

    def cell(r, col):  # r 1-based, col 1-based
        row = vals[r - 1] if 0 < r <= n else []
        return _norm(row[col - 1]) if col - 1 < len(row) else ""

    # --- Product Summary: ordered list of (first-header-row, key) ---
    # The team header normally sits in col B, but it drifts to col A when
    # someone re-pastes a block (Khalil's "KHALIL'S CAPTAIN TEAM" landed in A
    # 2026-07-25 — his whole section went missing AND Sahil's span silently
    # swallowed it). So: read col B, fall back to col A. Only col B drives the
    # "structural row" reset below, since col A also holds the WE-history dates.
    ps_hits: List[Tuple[int, str]] = []
    seen_key_last: Optional[str] = None
    for r in range(1, n + 1):
        b = cell(r, 2)
        hit: Optional[str] = None
        for text in (b, cell(r, 1)):
            if not text:
                continue
            hit = next((key for key, token in CAPTAIN_TOKEN.items()
                        if _is_ps_header(text, token)), None)
            if hit:
                break
        if hit:
            # Collapse the fiber/rafael duplicate ("ALL UNITS PERFORMANCE"
            # repeats the SAME captain header) into one span.
            if not (ps_hits and ps_hits[-1][1] == hit
                    and seen_key_last == hit):
                ps_hits.append((r, hit))
            seen_key_last = hit
        elif b:
            # A non-PS structural row (e.g. "RAF ORG - Current vs Prior")
            # ends the PS region for boundary purposes.
            seen_key_last = None

    # First-occurrence row per key, in sheet order.
    ps_first: Dict[str, int] = {}
    order: List[str] = []
    for row, key in ps_hits:
        if key not in ps_first:
            ps_first[key] = row
            order.append(key)

    # Back the start up over the block's PERFORMANCE banner. Done HERE, on the
    # shared dict, so the boundary math below sees one start per captain: if the
    # banner were added afterwards, the block above would still end at the
    # un-extended row and the two spans would overlap by the banner.
    for key in order:
        ps_first[key] = _banner_start(cell, ps_first[key])

    # --- Units charts: (header_row, key, subtype-label) ---
    # ALL "Total for week" anchor rows (captain blocks AND the interleaved
    # non-captain sections like RAF SPECIAL TEAM / TRANG'S ORG) — used to bound
    # each captain block's end, so a captain block never swallows a following
    # non-captain section.
    all_anchor_rows: List[int] = [r for r in range(1, n + 1)
                                  if cell(r, 3).lower() == _TOTAL_FOR_WEEK]
    # Same col B -> col A fallback as the PS headers above. A units label that
    # drifts to col A is WORSE than the PS case: it raises nothing, the captain
    # just silently loses their unit charts. The col-C "Total for week" anchor
    # keeps this tight, so reading col A too can't pull in unrelated rows.
    units_hits: List[Tuple[int, str, str]] = []
    for r in all_anchor_rows:
        c = cell(r, 3)
        for text in (cell(r, 2), cell(r, 1)):
            if not text:
                continue
            key = next((k for k, token in CAPTAIN_TOKEN.items()
                        if _is_units_header(text, c, token)), None)
            if key:
                # The sub-label ("NEW INTERNET UNITS" / "ALL UNITS") sits one
                # row under the header — and on the live board it is in col A,
                # not col B (checked 2026-08-25: every one of the 19 blocks has
                # a BLANK B there). Reading only col B made every label fall
                # back to "UNITS", which _units_label prints as "All Units", so
                # Rafael and the five fiber captains got two charts captioned
                # "All Units — <day>" and the New Internet one was mislabeled
                # (Eve, 2026-08-25). Same col B -> col A fallback the header
                # lookup above already does.
                sub = cell(r + 1, 2) or cell(r + 1, 1) or "UNITS"
                units_hits.append((r, key, sub))
                break

    first_units_row = all_anchor_rows[0] if all_anchor_rows else n + 1

    # PS block end = next distinct captain's PS header - 1 (last one bounded by
    # the units region), then trim trailing blanks.
    blocks: Dict[str, CaptainBlocks] = {}
    for i, key in enumerate(order):
        start = ps_first[key]
        nxt = ps_first[order[i + 1]] if i + 1 < len(order) else first_units_row
        # For the last PS block, also stop at the first "* ORG - Current"
        # summary that precedes the units region.
        end = nxt - 1
        if i + 1 >= len(order):
            # The last PS block is followed by the cross-org summary tables
            # ("RAF ORG (w/out Carlos)", "CARLOS ORG - Current vs Prior", …).
            # Stop at the first standalone-"ORG" header so the summary tables
            # don't bleed into the screenshot.
            for r in range(start + 1, first_units_row):
                if re.search(r"(?i)\bORG\b", cell(r, 2)):
                    end = r - 1
                    break
        end = _trim_trailing_blank(vals, start, end, 11)
        blocks[key] = CaptainBlocks(ps_start=start, ps_end=end, units=[])

    # Units block end = next "Total for week" anchor (of ANY kind) - 1,
    # trimmed — so a captain block stops before the next section even when
    # that section is a non-captain one (RAF SPECIAL TEAM, TRANG'S ORG).
    for (hr, key, sub) in units_hits:
        nxt = next((a for a in all_anchor_rows if a > hr), n + 1)
        end = _trim_trailing_blank(vals, hr, nxt - 1, 3)
        if key in blocks:
            blocks[key].units.append(
                UnitsBlock(label=sub, header_row=hr, start_row=hr, end_row=end))
    return blocks


def _day_col_map(header_row_vals: List[str]) -> Dict[str, int]:
    """day-name -> 1-based first column of its 3-col group, read from the
    units block's header row (never hardcoded F/I/L…)."""
    out: Dict[str, int] = {}
    for i, v in enumerate(header_row_vals):
        if _norm(v) in _DAYS:
            out[_norm(v)] = i + 1
    return out


def prior_day_columns(block: UnitsBlock, today: dt.date,
                      vals: Optional[List[List[str]]] = None
                      ) -> Tuple[str, str, str]:
    """(day_name, first_col_letter, last_col_letter) for the day BEFORE
    `today` in this units block (the 3-col group to show next to B:E).
    Spec: show B + C:E (Total for week) + the prior day's 3 columns."""
    vals = vals or _values()
    header = vals[block.header_row - 1] if block.header_row - 1 < len(vals) else []
    day_cols = _day_col_map(header)
    target = (today - dt.timedelta(days=1)).strftime("%A")
    col = day_cols.get(target)
    if col is None:  # fall back to the rightmost present day
        col = max(day_cols.values()) if day_cols else 6  # F
        target = next((d for d, c in day_cols.items() if c == col), target)
    return (target, rowcol_to_a1(1, col)[:-1], rowcol_to_a1(1, col + 2)[:-1])


# A vertical weekly-history row: col A reads "WE <date>" (e.g. "WE 7.19"). These
# runs sit at the bottom of each PS sub-block (fiber/Rafael have two: New
# Internet + All Units) and can stretch a full year back — we keep only the
# newest few for the screenshot.
_WE_HISTORY_RE = re.compile(r"(?i)^\s*WE\s")


def week_history_runs(ps_start: int, ps_end: int,
                      vals: Optional[List[List[str]]] = None) -> List[List[int]]:
    """Contiguous runs of 'WE <date>' history rows (col A) inside the PS span,
    in sheet order (newest week first within each run). One run per sub-block."""
    vals = vals or _values()

    def a(r: int) -> str:
        row = vals[r - 1] if 0 < r <= len(vals) else []
        return _norm(row[0]) if row else ""

    runs: List[List[int]] = []
    r = ps_start
    while r <= ps_end:
        if _WE_HISTORY_RE.match(a(r)):
            run: List[int] = []
            while r <= ps_end and _WE_HISTORY_RE.match(a(r)):
                run.append(r)
                r += 1
            runs.append(run)
        else:
            r += 1
    return runs


def ps_shot_plan(ps_start: int, ps_end: int, keep: int = 4,
                 vals=None) -> Tuple[List[Tuple[int, int]], int]:
    """Plan a last-`keep`-weeks Product Summary screenshot. Returns
    (hide_ranges, end_row):
      • hide_ranges — 0-based half-open ROW ranges to hide: the weeks past the
        newest `keep` in every sub-block EXCEPT the last one (those tails sit
        mid-block, between two sub-blocks, so they must be collapsed out).
      • end_row — 1-based last row to capture: the last sub-block's `keep`-th
        newest week. Its older weeks sit BELOW this, so the shot range simply
        stops here instead of hiding them — which also drops the trailing blanks
        and the next captain's header that would otherwise butt up against it."""
    runs = week_history_runs(ps_start, ps_end, vals)
    if not runs:
        return [], ps_end
    rows: List[int] = []
    for run in runs[:-1]:
        if len(run) > keep:
            rows.extend(run[keep:])
    last = runs[-1]
    end_row = last[keep - 1] if len(last) >= keep else ps_end
    merged: List[Tuple[int, int]] = []
    for r in sorted(set(rows)):
        if merged and r - 1 == merged[-1][1]:      # contiguous (0-based)
            merged[-1] = (merged[-1][0], r)
        else:
            merged.append((r - 1, r))
    return merged, end_row


@contextlib.contextmanager
def _rows_hidden(ranges: List[Tuple[int, int]]):
    """Temporarily set hiddenByUser on `ranges` (0-based half-open), clearing it
    on exit. No-op for an empty list."""
    if not ranges:
        yield 0
        return
    ws = _open_ws()

    def _set(hidden: bool):
        reqs = [{"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": s, "endIndex": e},
            "properties": {"hiddenByUser": hidden},
            "fields": "hiddenByUser"}} for (s, e) in ranges]
        ws.spreadsheet.batch_update({"requests": reqs})

    _set(True)
    try:
        yield sum(e - s for s, e in ranges)
    finally:
        _set(False)


def _user_hidden_rows(lo: int, hi: int) -> List[int]:
    """1-based rows in [lo, hi] a PERSON has hidden (hiddenByUser)."""
    ws = _open_ws()
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),"
                   "data(rowMetadata(hiddenByUser)))"})
    rm = next(((sh.get("data") or [{}])[0].get("rowMetadata") or []
               for sh in meta["sheets"]
               if sh["properties"]["sheetId"] == ws.id), [])
    return [r for r in range(lo, min(hi, len(rm)) + 1)
            if (rm[r - 1] or {}).get("hiddenByUser")]


@contextlib.contextmanager
def _rows_unhidden(rows: List[int]):
    """Temporarily REVEAL person-hidden `rows` (1-based), RE-HIDING them on
    exit. Mirror of _rows_hidden, and the asymmetry is the whole point: these
    rows were hidden by a HUMAN, so the restore must put hiddenByUser back to
    True. Never widen this to rows we didn't just reveal — restoring a row we
    found visible would silently hide someone's data."""
    if not rows:
        yield 0
        return
    ws = _open_ws()
    merged: List[Tuple[int, int]] = []          # 0-based half-open
    for r in sorted(set(rows)):
        if merged and r - 1 == merged[-1][1]:
            merged[-1] = (merged[-1][0], r)
        else:
            merged.append((r - 1, r))

    def _set(hidden: bool):
        reqs = [{"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": s, "endIndex": e},
            "properties": {"hiddenByUser": hidden},
            "fields": "hiddenByUser"}} for (s, e) in merged]
        ws.spreadsheet.batch_update({"requests": reqs})

    _set(False)
    try:
        yield len(rows)
    finally:
        _set(True)


def _col_index(letter: str) -> int:
    """'A' -> 0, 'L' -> 11, 'AA' -> 26."""
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


# A rendered column is its stored pixelSize plus one gridline. Measured on the
# Sales Board 2026-07-28: A:L is 1296 stored, 1308 rendered, for every row tried.
_GRIDLINE_PX = 1
# Rows do NOT follow their stored size — an auto-fit row reports 21 and draws at
# 24 or 27 depending on its font. So the stored row sum is only ever used to
# SIZE THE VIEWPORT, never to clip, and it is padded by this much first.
ROW_RENDER_SLACK = 1.6


def grid_span(end_col: str, row_start: int, row_end: int) -> Tuple[float, float]:
    """(rendered width, STORED height) in CSS px of A:`end_col` x
    `row_start`:`row_end`, skipping whatever is hidden right now. Call it INSIDE
    ps_shot_view — hidden state is part of the answer.

    The width is exact and is what the screenshot clips to. The height is only an
    estimate (see ROW_RENDER_SLACK); the caller measures the real one in the
    browser off a COLUMN-A-ONLY range.

    Why not just measure both in the browser: Sheets expands a selection to cover
    every merged cell it touches, in BOTH directions.
      • across — Chan's row-1058 merge reaches M, so his A:L overlay came back
        M-wide and put WE 05.24 (unformatted, not part of this report) in his
        email.
      • down — his M1059:M1114 merge drags the overlay 41 rows past the range
        end; the viewport then clipped it and the shot ended mid-row.
    A column-A range touches neither, which is why the height probe uses one.
    """
    ws = _open_ws()
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),data(columnMetadata("
                   "pixelSize,hiddenByUser,hiddenByFilter),rowMetadata("
                   "pixelSize,hiddenByUser,hiddenByFilter)))"})
    data = next(((sh.get("data") or [{}])[0] for sh in meta["sheets"]
                 if sh["properties"]["sheetId"] == ws.id), {})

    def _visible(md: List[dict], lo: int, hi: int) -> List[dict]:
        return [m for m in md[lo:hi]
                if not (m.get("hiddenByUser") or m.get("hiddenByFilter"))]

    cols = _visible(data.get("columnMetadata") or [], 0, _col_index(end_col) + 1)
    rows = _visible(data.get("rowMetadata") or [], row_start - 1, row_end)
    width = sum(c.get("pixelSize", 0) + _GRIDLINE_PX for c in cols)
    return float(width), float(sum(r.get("pixelSize", 0) for r in rows))


def merge_expanded_end_row(row_start: int, row_end: int, end_col: str) -> int:
    """The last row a selection of A`row_start`:`end_col``row_end` REALLY covers.

    Sheets grows a selection to contain every merged cell it touches, and the
    growth is transitive: on Chan's block the range reaches M (row-1058 merge
    spans A:M), M then brings in M1059:M1114, and the selection lands 41 rows
    below the range. The overlay is what the screenshot clips to, so those rows
    ride along into the email — his PS ran to WE 5.17 instead of stopping at the
    4th week. Fixpoint rather than one pass, because each expansion can touch
    merges the last one didn't."""
    ws = _open_ws()
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),merges)"})
    merges = next((sh.get("merges", []) for sh in meta["sheets"]
                   if sh["properties"]["sheetId"] == ws.id), [])
    r0, r1 = row_start - 1, row_end                 # 0-based, half-open
    c0, c1 = 0, _col_index(end_col) + 1
    for _ in range(12):                             # converges in 2-3
        grew = False
        for m in merges:
            ms, me = m.get("startRowIndex", 0), m.get("endRowIndex", 0)
            ns, ne = m.get("startColumnIndex", 0), m.get("endColumnIndex", 0)
            if ms < r1 and me > r0 and ns < c1 and ne > c0:
                if ms < r0 or me > r1 or ns < c0 or ne > c1:
                    r0, r1 = min(r0, ms), max(r1, me)
                    c0, c1 = min(c0, ns), max(c1, ne)
                    grew = True
        if not grew:
            break
    return r1


@contextlib.contextmanager
def ps_shot_view(ps_start: int, ps_end: int, keep_weeks: int = 4):
    """Sheet view state for a Product Summary screenshot: EXPAND the collapsed
    weekly-history groups (so weeks 2..keep_weeks are visible), HIDE the
    mid-block older weeks, and REVEAL any of the kept weeks a person had
    hidden. Yields the 1-based `end_row` the caller should use as the capture
    range end (trims the last sub-block's older weeks + trailing chrome). All
    edits are restored on exit — same accepted shared-view model as
    ps_groups_expanded.

    Why the reveal step: ps_shot_plan picks the newest `keep_weeks` rows
    POSITIONALLY, so a week row hidden by hand inside that window silently
    shrinks the shot to fewer than keep_weeks weeks (Khalil, 2026-07-25: rows
    1387-1389 hidden -> the PS rendered 2 weeks, not 4, with no error). We
    reveal rather than skip-and-walk-further on purpose: skipping would emit
    4 rows spanning NON-CONSECUTIVE weeks, silently dropping real data and
    reading as if it were the last 4 weeks. Scoped to week-history rows only,
    so a rep row someone hid deliberately stays hidden.

    The reveal list EXCLUDES whatever the plan is hiding. Both lists are week
    rows, and the reveal is measured before the groups are expanded — so with the
    groups COLLAPSED (their rows read as hiddenByUser) every older week landed in
    both lists, and the reveal, running last, undid the hide. Chan's PS then
    showed all 10 weeks instead of 4 (2026-07-29). Whether it happened at all
    depended on how someone had left the groups, which is why it stayed hidden
    for weeks."""
    vals = _values()
    ranges, end_row = ps_shot_plan(ps_start, ps_end, keep_weeks, vals)
    # Collapse the rows the selection would be dragged into below the cut, so the
    # overlay ends where the range does. They are restored on exit like the rest.
    tail_end = merge_expanded_end_row(ps_start, end_row, PS_END_COL)
    if tail_end > end_row:
        ranges = ranges + [(end_row, tail_end)]     # 0-based half-open
    planned_hidden = {r for s, e in ranges for r in range(s + 1, e + 1)}
    week_rows = {r for run in week_history_runs(ps_start, ps_end, vals)
                 for r in run} - planned_hidden
    reveal = [r for r in _user_hidden_rows(ps_start, end_row)
              if r in week_rows]
    with ps_groups_expanded(ps_start, ps_end):
        with _rows_hidden(ranges):
            with _rows_unhidden(reveal):
                yield end_row


@contextlib.contextmanager
def ps_groups_expanded(ps_start: int, ps_end: int):
    """Temporarily EXPAND every collapsed row group overlapping the Product
    Summary span (the vertical weekly historicals live in those groups),
    restoring the prior collapsed state on exit. Group collapse state is
    SHARED — viewers see the groups expanded during the shot (~30-60s).
    Approved by Megan 2026-06-04. Yields the number of groups expanded."""
    ws = _open_ws()
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),rowGroups)"})
    groups = next((sh.get("rowGroups", []) for sh in meta["sheets"]
                   if sh["properties"]["sheetId"] == ws.id), [])
    to_expand = [g for g in groups
                 if g.get("collapsed", False)
                 and g["range"].get("startIndex", 0) < ps_end
                 and g["range"].get("endIndex", 0) > ps_start - 1]

    def _set(collapsed: bool):
        reqs = []
        for g in to_expand:
            rng = dict(g["range"])
            rng.setdefault("sheetId", ws.id)
            rng.setdefault("dimension", "ROWS")
            reqs.append({"updateDimensionGroup": {
                "dimensionGroup": {"range": rng, "depth": g["depth"],
                                   "collapsed": collapsed},
                "fields": "collapsed"}})
        if reqs:
            ws.spreadsheet.batch_update({"requests": reqs})

    _set(False)
    try:
        yield len(to_expand)
    finally:
        _set(True)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    blocks = discover_blocks()
    for key in CAPTAIN_TOKEN:
        b = blocks.get(key)
        if not b:
            print(f"{key:8s}  (no blocks found)")
            continue
        u = ", ".join(f"{x.label}@{x.start_row}-{x.end_row}" for x in b.units)
        print(f"{key:8s}  PS A{b.ps_start}:{PS_END_COL}{b.ps_end}   units[{len(b.units)}]: {u}")
