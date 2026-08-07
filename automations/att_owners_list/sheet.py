"""Read, diff and write the 'ATT Owners List' tab.

THE TAB IS A MATRIX: one column per week, one row per person.

    row 1   year band        2025 …………………………… 2026 ……………………
    row 2   month band       September 2025 | October 2025 | …
    row 3   week header      'update for WE' | 9/28 | 10/5 | … | 8/2 | 8/9
    rows 4+ one per owner    their NAME repeated across the weeks they sold

THE COLOUR LANGUAGE (read off the live tab 2026-08-07 and 100% consistent
across all 46 columns × 97 rows — this module writes exactly these three):

    name on WHITE     #ffffff  sold that week
    name on YELLOW    #fff2cc  their FIRST week — a NEW owner in the program
    blank on RED      #f4cccc  in the program before, no sales this week
    blank on YELLOW   #fff2cc  every week BEFORE they ever appeared

So yellow always means "not in the program yet (this is where they start)" and
red always means "was in, isn't this week". A red cell is deliberately NOT a
removal: the person keeps their row and their history for good, and the weeks
tell you whether it was one quiet week or the end [[feedback_fill_but_flag]].
Once someone has appeared, EVERY later column carries either their name or a
red cell — Linda Villalobos has been red since 11/9 and Tomas Meza since 1/18.

ROW IDENTITY. Rows are matched by NAME, never by position, and a name that
occupies more than one row resolves to the row where it appears in the
RIGHTMOST (most recent) column. That matters because the tab has real
misalignment in its history: the 4/19 and 4/26 columns were pasted one row low,
so rows 28-100 hold the previous person's name in those two columns, Eric
Martinez and Eric Zech never came back into line, and rows 99/100 exist only as
the overflow. `health(grid)` reports it; `plan_rebuild` fixes it losslessly.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.org_sales_board.fill_section import _col, _cell

HEADER_LABEL = "update for we"          # col A of the week-header row

def _rgb(hexcode: str) -> dict:
    """#RRGGBB → the API's 0-1 floats, as EXACT n/255 fractions.

    Not a nicety: Sheets stores a colour by truncating (not rounding) f*255, so
    the 0.949 that reads back off the existing yellow re-writes as 241/255 and
    the new cells sit one byte away from the ones beside them. Feeding it the
    exact fraction round-trips."""
    h = hexcode.lstrip("#")
    return {k: int(h[i:i + 2], 16) / 255
            for k, i in (("red", 0), ("green", 2), ("blue", 4))}


YELLOW = _rgb("#FFF2CC")        # not in the program yet / their first week
RED = _rgb("#F4CCCC")           # was in the program, no sales this week
WHITE = _rgb("#FFFFFF")
GRAY = _rgb("#D9D9D9")          # the week-header row
BAND = _rgb("#C9DAF8")          # the year / month bands

# The summary block written under the names (see `plan_summary`). Located by
# these col-A labels every run, so the name rows can grow into the gap without
# anyone maintaining a row number.
SUM_TOTAL = "OWNERS IN PROGRAM"
SUM_NEW = "NEW THIS WEEK"
SUM_OUT = "NOT SELLING THIS WEEK"
SUMMARY_LABELS = (SUM_TOTAL, SUM_NEW, SUM_OUT)

_MONTHS = ("January February March April May June July August September "
           "October November December").split()


# --------------------------------------------------------------- name keys
def name_key(raw: str) -> str:
    """Normalized comparison key. Case, punctuation and the curly/straight
    apostrophe all differ between Tableau and the tab ("ANDRE’ BURTON JR." vs
    "Andre' Burton"), and none of them make it a different person."""
    s = (raw or "").strip()
    s = s.replace("’", "'").replace("‘", "'")
    s = re.split(r"[\[\n]", s, maxsplit=1)[0]
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"[^a-z0-9' -]", " ", s.lower())
    return " ".join(s.split())


def candidates(raw: str, aliases: Optional[dict] = None) -> set:
    """Every key this person could be filed under: the name itself plus every
    ICD-Aliases spelling of it. Keeps a rename from reading as one person
    leaving and another arriving. [[project_icd-aliases-direction]]"""
    forms = {raw}
    if aliases:
        from automations.org_sales_board.fill_section import alias_to_canonical
        canon = alias_to_canonical(raw, aliases)
        forms.add(canon)
        forms.update(aliases.get(canon, []))
    return {name_key(f) for f in forms if f}


# ------------------------------------------------------------------ layout
@dataclass
class Layout:
    header_row: int                       # the 'update for WE' row (3)
    year_row: int
    month_row: int
    first_name_row: int
    last_name_row: int
    week_cols: Dict[dt.date, int]         # week-ending Sunday → 1-indexed col
    rows_by_key: Dict[str, int]           # name key → row
    display: Dict[int, str]               # row → the name as the tab spells it
    summary_rows: Dict[str, int] = field(default_factory=dict)

    @property
    def weeks(self) -> List[dt.date]:
        return sorted(self.week_cols)

    def col_for(self, sunday: dt.date) -> Optional[int]:
        return self.week_cols.get(sunday)

    def filled_weeks(self, grid) -> List[dt.date]:
        """Weeks that actually carry names (the header row runs ahead of the
        data — 8/9, 8/16 and 8/23 were typed in advance)."""
        out = []
        for wk in self.weeks:
            c = self.week_cols[wk]
            if any(_cell(grid, r - 1, c - 1)
                   for r in range(self.first_name_row, self.last_name_row + 1)):
                out.append(wk)
        return out


def _parse_header_date(raw: str, year: int) -> Optional[dt.date]:
    m = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})$", (raw or "").strip())
    if not m:
        return None
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def find_layout(grid: List[List[str]]) -> Layout:
    hdr = next((r for r in range(1, len(grid) + 1)
                if _cell(grid, r - 1, 0).lower() == HEADER_LABEL), None)
    if hdr is None:
        raise ValueError(f"no week-header row (col A == {HEADER_LABEL!r})")
    year_row, month_row = max(1, hdr - 2), max(1, hdr - 1)

    # Year comes off the bands, but the bands are sparse ('2026' appears once,
    # the month band stops updating in July) so it is carried forward and then
    # CORRECTED by monotonicity: these columns are chronological, so a date that
    # doesn't move forward is a year boundary, not a typo. That is what makes a
    # December→January run land in the right year with no special case.
    week_cols: Dict[dt.date, int] = {}
    year, prev = None, None
    for c in range(2, len(grid[hdr - 1]) + 1):
        band_y = _cell(grid, year_row - 1, c - 1)
        if re.fullmatch(r"20\d{2}", band_y):
            year = int(band_y)
        band_m = _cell(grid, month_row - 1, c - 1)
        m = re.match(r"^([A-Za-z]+)\s+(20\d{2})$", band_m)
        if m and m.group(1).capitalize() in _MONTHS:
            year = int(m.group(2))
        raw = _cell(grid, hdr - 1, c - 1)
        if not raw:
            continue
        d = _parse_header_date(raw, year or dt.date.today().year)
        if d is None:
            continue
        while prev is not None and d <= prev:
            d = d.replace(year=d.year + 1)
        week_cols[d] = c
        prev, year = d, d.year

    # Name rows: everything under the header until the summary block (a col-A
    # label) or the end of the used grid.
    first = hdr + 1
    last = first - 1
    summary: Dict[str, int] = {}
    for r in range(first, len(grid) + 1):
        label = _cell(grid, r - 1, 0).strip().upper()
        if label in SUMMARY_LABELS:
            summary[label] = r
            continue
        if summary:
            continue
        if any(_cell(grid, r - 1, c - 1) for c in range(2, len(grid[r - 1]) + 1)):
            last = r

    # A name can sit on more than one row (see the module docstring). The row
    # where it appears most RECENTLY is the live one.
    best: Dict[str, Tuple[int, int]] = {}          # key → (rightmost col, row)
    display: Dict[int, str] = {}
    for r in range(first, last + 1):
        rightmost = None
        for c in range(2, len(grid[r - 1]) + 1 if r - 1 < len(grid) else 2):
            n = _cell(grid, r - 1, c - 1)
            if not n:
                continue
            rightmost = n
            k = name_key(n)
            if k not in best or c > best[k][0]:
                best[k] = (c, r)
        if rightmost:
            display[r] = rightmost
    return Layout(header_row=hdr, year_row=year_row, month_row=month_row,
                  first_name_row=first, last_name_row=last,
                  week_cols=week_cols,
                  rows_by_key={k: v[1] for k, v in best.items()},
                  display=display, summary_rows=summary)


# -------------------------------------------------------------------- diff
@dataclass
class WeekPlan:
    sunday: dt.date
    col: int
    compared_to: Optional[dt.date]        # the previous week with data
    new: List[str] = field(default_factory=list)        # first week ever
    back: List[str] = field(default_factory=list)       # returning after a gap
    kept: List[str] = field(default_factory=list)       # sold both weeks
    dropped: List[str] = field(default_factory=list)    # sold last week, not now
    still_out: List[str] = field(default_factory=list)  # out for longer
    ghosts: List[str] = field(default_factory=list)     # duplicate leftover rows
    unmatched_rows: List[str] = field(default_factory=list)
    values: List[dict] = field(default_factory=list)    # A1 → [[value]]
    fills: List[Tuple[int, int, dict]] = field(default_factory=list)  # r0,r1,color
    inserts: List[Tuple[str, int]] = field(default_factory=list)      # name,row
    log: List[str] = field(default_factory=list)

    @property
    def in_program(self) -> int:
        return len(self.new) + len(self.back) + len(self.kept)


def _sorts_before(a: str, b: str) -> bool:
    return a.upper() < b.upper()


def plan_week(grid, layout: Layout, pull, *, aliases: Optional[dict] = None,
              logfn=print) -> WeekPlan:
    """Diff the pull against the tab and lay out every write for the week.

    Pure — no Sheet I/O — so the whole thing can be printed before anything is
    touched. Rows for people who are new get an INSERT (alphabetical, so the
    column keeps reading top-to-bottom like the ones beside it); nothing is ever
    deleted or moved."""
    sunday = pull.week_ending
    col = layout.col_for(sunday)
    if col is None:
        raise ValueError(f"no column for WE {sunday.isoformat()} — call "
                         f"ensure_week_col() first")
    filled = [w for w in layout.filled_weeks(grid) if w < sunday]
    prev = filled[-1] if filled else None
    plan = WeekPlan(sunday=sunday, col=col, compared_to=prev)

    prev_names = set()
    if prev is not None:
        pc = layout.week_cols[prev]
        prev_names = {name_key(_cell(grid, r - 1, pc - 1))
                      for r in range(layout.first_name_row,
                                     layout.last_name_row + 1)
                      if _cell(grid, r - 1, pc - 1)}

    # --- match every pulled owner to a row -------------------------------
    # NEW is decided by HISTORY, not by "did we have to insert a row": a second
    # run of the same week finds the row it just created, and calling that
    # person "back after a gap" would rewrite last hour's news. Someone is new
    # when no column BEFORE this week carries their name.
    row_for: Dict[str, int] = {}
    for o in pull.owners:
        cands = candidates(o.name, aliases)
        hit = next((layout.rows_by_key[k] for k in cands
                    if k in layout.rows_by_key), None)
        if hit is not None:
            row_for[o.name] = hit
        seen_before = hit is not None and any(
            _cell(grid, hit - 1, c - 1)
            for w, c in layout.week_cols.items() if w < sunday)
        if not seen_before:
            plan.new.append(o.name)
        elif not (cands & prev_names):
            plan.back.append(o.name)
        else:
            plan.kept.append(o.name)

    # --- where each new person's row goes (alphabetical, like the column) --
    taken = sorted(layout.display.items())
    for name in plan.new:
        if name in row_for:            # already has a row, just never filled
            continue
        at = next((r for r, disp in taken if _sorts_before(name, disp)),
                  layout.last_name_row + 1)
        plan.inserts.append((name, at))

    # --- every existing row: name, or a red blank -------------------------
    # A person can own MORE THAN ONE row (the 4/19-4/26 paste damage — see the
    # module docstring): the live row is the one their name reaches furthest
    # right, and the others are leftovers. A leftover must not be painted red,
    # or someone who is selling fine reads as "stopped selling" on the tab and
    # in the Slack note. It gets a plain blank and a mention in the log.
    hit_rows = set(row_for.values())
    live_keys = {name_key(n) for n in row_for}
    for r in range(layout.first_name_row, layout.last_name_row + 1):
        disp = layout.display.get(r)
        if disp is None:                       # a spacer row inside the block
            continue
        if r in hit_rows:
            name = next(n for n, rr in row_for.items() if rr == r)
            plan.values.append({"range": f"{_col(col)}{r}", "values": [[name]]})
            # YELLOW when this is the first week their row carries a name —
            # the tab's "new to the program" mark. Derived from the row itself
            # rather than from "did we just insert it", so a row that was
            # created early (or by hand) still gets marked on their real first
            # week.
            seen_before = any(_cell(grid, r - 1, c - 1)
                              for w, c in layout.week_cols.items() if w < sunday)
            plan.fills.append((r, r, YELLOW if not seen_before else WHITE))
            continue
        plan.values.append({"range": f"{_col(col)}{r}", "values": [[""]]})
        if name_key(disp) in live_keys:
            plan.fills.append((r, r, WHITE))
            plan.ghosts.append(f"row {r} ({disp})")
            continue
        plan.fills.append((r, r, RED))
        plan.unmatched_rows.append(disp)
        if name_key(disp) in prev_names:
            plan.dropped.append(disp)
        else:
            plan.still_out.append(disp)

    plan.log.append(
        f"  WE {sunday.isoformat()} → column {_col(col)}"
        + (f"; compared against WE {prev.isoformat()} "
           f"({_col(layout.week_cols[prev])})" if prev else "; nothing to "
           "compare against (first filled week)"))
    plan.log.append(
        f"  {plan.in_program} owner(s) in the program: {len(plan.kept)} kept, "
        f"{len(plan.back)} returning, {len(plan.new)} new")
    plan.log.append(
        f"  {len(plan.dropped)} stopped selling this week, "
        f"{len(plan.still_out)} already out (still red)")
    if plan.ghosts:
        plan.log.append(
            f"  {len(plan.ghosts)} leftover row(s) left blank (the person's "
            f"live row is elsewhere — `--rebuild` merges them): "
            f"{', '.join(plan.ghosts[:5])}"
            + (" …" if len(plan.ghosts) > 5 else ""))
    return plan


# ------------------------------------------------------------------ writes
def _repeat_cell(sheet_id: int, r0: int, r1: int, c0: int, c1: int,
                 color: dict) -> dict:
    """r/c are 1-indexed inclusive."""
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": r0 - 1,
                  "endRowIndex": r1, "startColumnIndex": c0 - 1,
                  "endColumnIndex": c1},
        "cell": {"userEnteredFormat": {"backgroundColor": color}},
        "fields": "userEnteredFormat.backgroundColor"}}


def _runs(fills: List[Tuple[int, int, dict]]) -> List[Tuple[int, int, dict]]:
    """Collapse per-row fills into contiguous same-colour runs — 97 rows is 6
    requests instead of 97."""
    out: List[List] = []
    for r0, r1, color in sorted(fills, key=lambda f: f[0]):
        if out and out[-1][2] == color and out[-1][1] + 1 == r0:
            out[-1][1] = r1
        else:
            out.append([r0, r1, color])
    return [(a, b, c) for a, b, c in out]


def ensure_week_col(ws, grid, sunday: dt.date, *, dry_run: bool = False,
                    logfn=print) -> Tuple[int, bool]:
    """The column for `sunday`, inserting one in date order if it is missing.

    The tab is typed a few weeks ahead by hand, so this is normally a no-op —
    but a week nobody pre-typed must not silently land in the wrong column
    (5/3, 7/5 and 7/26 are missing from the history for exactly that reason)."""
    layout = find_layout(grid)
    have = layout.col_for(sunday)
    if have:
        return have, False
    later = [w for w in layout.weeks if w > sunday]
    at = layout.week_cols[later[0]] if later else (max(layout.week_cols.values()) + 1)
    label = f"{sunday.month}/{sunday.day}"
    logfn(f"  + no column for WE {label} — inserting one at {_col(at)}")
    if dry_run:
        return at, True
    ws.spreadsheet.batch_update({"requests": [
        {"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": at - 1, "endIndex": at},
            "inheritFromBefore": True}},
        _repeat_cell(ws.id, layout.year_row, layout.month_row, at, at, BAND),
        _repeat_cell(ws.id, layout.header_row, layout.header_row, at, at, GRAY),
        _repeat_cell(ws.id, layout.first_name_row, max(
            layout.last_name_row, layout.first_name_row), at, at, WHITE),
    ]})
    data = [{"range": f"{ws.title}!{_col(at)}{layout.header_row}",
             "values": [[label]]}]
    # Only stamp the month band when the month actually changes, which is how
    # the existing bands read.
    prevs = [w for w in layout.weeks if w < sunday]
    if not prevs or prevs[-1].month != sunday.month:
        data.append({"range": f"{ws.title}!{_col(at)}{layout.month_row}",
                     "values": [[f"{_MONTHS[sunday.month - 1]} {sunday.year}"]]})
    if not prevs or prevs[-1].year != sunday.year:
        data.append({"range": f"{ws.title}!{_col(at)}{layout.year_row}",
                     "values": [[str(sunday.year)]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    return at, True


def apply_inserts(ws, plan: WeekPlan, layout: Layout, *, logfn=print) -> None:
    """Insert each new owner's row, bottom-up so the earlier positions in the
    plan stay valid, and paint the yellow lead-in that says 'new'."""
    if not plan.inserts:
        return
    reqs, data = [], []
    for name, at in sorted(plan.inserts, key=lambda t: t[1], reverse=True):
        reqs.append({"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": at - 1, "endIndex": at},
            "inheritFromBefore": False}})
    ws.spreadsheet.batch_update({"requests": reqs})
    # Row numbers shift as rows above them are added; recompute after the fact.
    shift = 0
    for name, at in sorted(plan.inserts, key=lambda t: t[1]):
        row = at + shift
        shift += 1
        # The lead-in only: the target cell itself is painted by apply_week,
        # which decides yellow-vs-white off the row's own history.
        reqs2 = [_repeat_cell(ws.id, row, row, 2, max(2, plan.col - 1), YELLOW)]
        ws.spreadsheet.batch_update({"requests": reqs2})
        data.append({"range": f"{ws.title}!{_col(plan.col)}{row}",
                     "values": [[name]]})
        logfn(f"    + {name} → new row {row} (yellow through "
              f"{_col(plan.col)}, the week they joined)")
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})


def apply_week(ws, plan: WeekPlan, *, logfn=print) -> None:
    """Write the week's column: names + the three fills."""
    if plan.values:
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": f"{ws.title}!{u['range']}", "values": u["values"]}
                     for u in plan.values]})
    runs = _runs(plan.fills)
    if runs:
        ws.spreadsheet.batch_update({"requests": [
            _repeat_cell(ws.id, r0, r1, plan.col, plan.col, color)
            for r0, r1, color in runs]})
    logfn(f"  wrote {len(plan.values)} cell(s) and {len(runs)} colour run(s) "
          f"in column {_col(plan.col)}")


# ---------------------------------------------------------------- summary
def plan_summary(grid, layout: Layout) -> Tuple[List[dict], List[dict]]:
    """Three count rows under the names, recomputed for EVERY week column from
    the tab itself: how many owners the program had, how many were new that
    week, and how many stopped selling. Values, not formulas — the counts are a
    diff between two columns, which no formula reads cleanly, and this way the
    whole history is filled in on the first run instead of only from now on.

    Returns (value updates, format requests)."""
    weeks = layout.weeks
    rows = {}
    base = layout.summary_rows or {}
    if base:
        rows = dict(base)
    else:                                   # first run — park them under the
        start = layout.last_name_row + 2    # names with one blank row of air
        rows = {lbl: start + i for i, lbl in enumerate(SUMMARY_LABELS)}

    def names_at(col: int) -> set:
        return {name_key(_cell(grid, r - 1, col - 1))
                for r in range(layout.first_name_row, layout.last_name_row + 1)
                if _cell(grid, r - 1, col - 1)}

    updates = [{"range": f"A{rows[lbl]}", "values": [[lbl]]}
               for lbl in SUMMARY_LABELS]
    seen: set = set()
    prev: Optional[set] = None
    for wk in weeks:
        c = layout.week_cols[wk]
        cur = names_at(c)
        if not cur:                         # a week typed ahead — leave it clear
            updates += [{"range": f"{_col(c)}{rows[lbl]}", "values": [[""]]}
                        for lbl in SUMMARY_LABELS]
            continue
        new = len(cur - seen)
        out = len(prev - cur) if prev is not None else 0
        updates += [
            {"range": f"{_col(c)}{rows[SUM_TOTAL]}", "values": [[len(cur)]]},
            {"range": f"{_col(c)}{rows[SUM_NEW]}", "values": [[new]]},
            {"range": f"{_col(c)}{rows[SUM_OUT]}", "values": [[out]]}]
        seen |= cur
        prev = cur
    fmts = []
    if not base:                            # style the block once, on creation
        for r in rows.values():
            fmts.append({"repeatCell": {
                "range": {"sheetId": None, "startRowIndex": r - 1,
                          "endRowIndex": r, "startColumnIndex": 0,
                          "endColumnIndex": max(layout.week_cols.values())},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": BAND,
                    "textFormat": {"bold": True, "fontSize": 12}}},
                "fields": ("userEnteredFormat.backgroundColor,"
                           "userEnteredFormat.textFormat")}})
    return updates, fmts


def apply_summary(ws, updates: List[dict], fmts: List[dict], *,
                  logfn=print) -> None:
    if fmts:
        for f in fmts:
            f["repeatCell"]["range"]["sheetId"] = ws.id
        ws.spreadsheet.batch_update({"requests": fmts})
    if updates:
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": f"{ws.title}!{u['range']}",
                      "values": u["values"]} for u in updates]})
    logfn(f"  summary block: {len(updates)} cell(s) refreshed")


def freeze_header(ws, layout: Layout) -> None:
    """Keep the year / month / week rows on screen while scrolling the names."""
    props = ws._properties.get("gridProperties", {}) or {}
    if props.get("frozenRowCount") == layout.header_row:
        return
    ws.spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id,
                       "gridProperties": {"frozenRowCount": layout.header_row}},
        "fields": "gridProperties.frozenRowCount"}}]})


# ----------------------------------------------------------------- health
def health(grid, layout: Layout) -> List[str]:
    """Everything about the tab that a human should know before trusting a
    diff off it. Reported, never auto-fixed."""
    out: List[str] = []
    # 1. rows carrying more than one person (the paste-one-row-low damage)
    bad = []
    for r in range(layout.first_name_row, layout.last_name_row + 1):
        names = {_cell(grid, r - 1, c - 1)
                 for c in layout.week_cols.values()
                 if _cell(grid, r - 1, c - 1)}
        if len(names) > 1:
            bad.append((r, sorted(names)))
    if bad:
        out.append(f"  ⚠ {len(bad)} row(s) hold more than one person — the tab "
                   f"was pasted one row low at some point, so 'row = person' "
                   f"is broken there. `--rebuild` realigns it losslessly.")
        for r, names in bad[:6]:
            out.append(f"      row {r}: {', '.join(names)}")
        if len(bad) > 6:
            out.append(f"      … and {len(bad) - 6} more")
    # 2. weeks with no column at all
    weeks = layout.weeks
    gaps = []
    for a, b in zip(weeks, weeks[1:]):
        step = (b - a).days
        if step > 7:
            gaps += [(a + dt.timedelta(days=7 * i)).isoformat()
                     for i in range(1, step // 7)]
    if gaps:
        out.append(f"  ⚠ {len(gaps)} week(s) have no column at all "
                   f"(nobody updated the tab those Fridays): {', '.join(gaps)}")
    return out


# ---------------------------------------------------------------- rebuild
def plan_rebuild(grid, layout: Layout) -> Tuple[List[List[str]], dict]:
    """Rebuild the name block so every row is ONE person, alphabetically.

    LOSSLESS BY CONSTRUCTION: the data on this tab is 'which names were in
    column X', and that SET is preserved column for column — only the row a
    name sits on changes. `verify_rebuild` asserts exactly that before anything
    is written, so a rebuild that would drop or invent a name cannot be applied.

    Returns (block, stats) where block is the new rows × week-columns grid."""
    cols = [layout.week_cols[w] for w in layout.weeks]
    per_col = {c: [] for c in cols}
    for c in cols:
        for r in range(layout.first_name_row, layout.last_name_row + 1):
            n = _cell(grid, r - 1, c - 1)
            if n:
                per_col[c].append(n)
    # One row per distinct person, keeping the tab's own spelling (the most
    # recent one if it ever changed).
    latest: Dict[str, str] = {}
    for c in cols:
        for n in per_col[c]:
            latest[name_key(n)] = n
    order = sorted(latest.values(), key=lambda s: s.upper())
    index = {name_key(n): i for i, n in enumerate(order)}
    block = [["" for _ in cols] for _ in order]
    for ci, c in enumerate(cols):
        for n in per_col[c]:
            block[index[name_key(n)]][ci] = n
    stats = {"people": len(order), "rows_before":
             layout.last_name_row - layout.first_name_row + 1,
             "weeks": len(cols)}
    return block, stats


def verify_rebuild(grid, layout: Layout, block: List[List[str]]) -> List[str]:
    """Per-column set equality between the tab and the rebuilt block."""
    problems = []
    for ci, wk in enumerate(layout.weeks):
        c = layout.week_cols[wk]
        before = {name_key(_cell(grid, r - 1, c - 1))
                  for r in range(layout.first_name_row, layout.last_name_row + 1)
                  if _cell(grid, r - 1, c - 1)}
        after = {name_key(row[ci]) for row in block if row[ci]}
        if before != after:
            problems.append(
                f"WE {wk.isoformat()}: {sorted(before - after)} lost, "
                f"{sorted(after - before)} invented")
    return problems


def apply_rebuild(ws, layout: Layout, block: List[List[str]], *,
                  logfn=print) -> None:
    """Write the rebuilt block — values AND colours — as ONE updateCells over
    the whole rectangle. A cell-by-cell repaint would be ~4,000 requests; this
    is one, and it can't half-apply and leave the tab in a mixed state."""
    cols = [layout.week_cols[w] for w in layout.weeks]
    c0, c1 = min(cols), max(cols)
    colors = {(r, c): col for r, c, col in rebuild_colors(block)}
    rows_payload = []
    for ri in range(len(block)):
        cells = []
        for c in range(c0, c1 + 1):
            ci = cols.index(c) if c in cols else None
            val = block[ri][ci] if ci is not None else ""
            color = colors.get((ri, ci), WHITE) if ci is not None else WHITE
            cell = {"userEnteredFormat": {"backgroundColor": color}}
            if val:
                cell["userEnteredValue"] = {"stringValue": val}
            cells.append(cell)
        rows_payload.append({"values": cells})
    # Anything below the rebuilt block inside the old name range is now empty.
    tail = layout.last_name_row - (layout.first_name_row + len(block) - 1)
    for _ in range(max(0, tail)):
        rows_payload.append({"values": [
            {"userEnteredFormat": {"backgroundColor": WHITE}}
            for _ in range(c0, c1 + 1)]})
    ws.spreadsheet.batch_update({"requests": [{"updateCells": {
        "range": {"sheetId": ws.id,
                  "startRowIndex": layout.first_name_row - 1,
                  "endRowIndex": layout.first_name_row - 1 + len(rows_payload),
                  "startColumnIndex": c0 - 1, "endColumnIndex": c1},
        "rows": rows_payload,
        "fields": "userEnteredValue,userEnteredFormat.backgroundColor"}}]})
    logfn(f"  rebuilt {len(block)} person row(s) × {len(cols)} week(s)"
          + (f", cleared {tail} leftover row(s)" if tail > 0 else ""))


def rebuild_colors(block: List[List[str]]) -> List[Tuple[int, int, dict]]:
    """(row_index, col_index, colour) for the rebuilt block, straight from the
    colour language: yellow up to and including the first week, white on a
    name, red on a blank after that first week."""
    # Weeks past the last one anybody has data for are typed AHEAD of the fill
    # (8/9, 8/16 and 8/23 already have headers). They are not "in the program
    # and not selling" — they haven't happened. Leave them clear.
    last_live = max((ci for row in block for ci, v in enumerate(row) if v),
                    default=-1)
    out = []
    for ri, row in enumerate(block):
        first = next((ci for ci, v in enumerate(row) if v), None)
        if first is None:
            continue
        for ci, v in enumerate(row):
            if ci > last_live:
                out.append((ri, ci, WHITE))
            elif ci <= first:
                out.append((ri, ci, YELLOW if not v or ci == first else WHITE))
            elif v:
                out.append((ri, ci, WHITE))
            else:
                out.append((ri, ci, RED))
    return out
