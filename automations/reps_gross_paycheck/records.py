"""The thing we write: the per-rep tabs of the Rep Records workbook.

TAB SHAPE (read fresh every run — it is NOT the same on every tab)

  row 1   | <rep name> | 6/21 | 6/28 | 7/5 | ...      |  | Monthly Expenses ...
  row n   | Gross Paycheck |  -  | $600 | $600 | ...

  * The week headers are LIVE FORMULAS. B1 holds a real date serial and every
    header after it is '=<previous>+7', so extending the run of weeks is one
    '=X1+7' — never a typed date that can drift out of step.
  * 'Gross Paycheck' is on row 4, 5 or 6 depending on when the tab was made,
    so it is found by its col-A label. Same for the week columns: found by
    reading the date serials out of row 1. [[no hardcoded rows or columns]]
  * The week run is FINITE. A tab made in June carries nine weekly columns and
    then the household-expenses block starts. Filling a week past the end
    means growing the run first — see `plan_extension`.

WHAT GOES IN THE CELL
  money in the PNL          -> the number
  no money (or a zero)      -> '-'
  rep is terminated         -> nothing at all; the cell is left exactly as is

'-' is Eve's own convention, already on the tabs (Amberly Chum's first week,
Zoria Johnson's). It's what separates "checked, nothing to pay" from "nobody
ran the report", which a blank cell cannot say.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.reps_gross_paycheck import names

SHEET_ID = "1einjzUF1C4MzosbZPxDsAKpGZCi2ud4ckaD8L2gqaXM"

GP_LABEL = "gross paycheck"
DASH = "-"
# Tabs that are scaffolding, not people.
TEMPLATE_MARKER = "template"

# Sheets serial-date epoch (1900 date system, as Google uses it).
EPOCH = dt.date(1899, 12, 30)

# How far a tab's week run may be grown in one go. A tab whose last week is
# further behind than this is a leftover from a previous season (a dozen of
# them end in Nov 2025) — growing those by thirty-odd columns to reach today
# would wreck the layout, so they're reported and left alone.
MAX_EXTEND_WEEKS = 8

CURRENCY_FORMAT = {"type": "CURRENCY", "pattern": '"$"#,##0'}
DATE_FORMAT = {"type": "DATE", "pattern": "m/d"}


def a1_col(n: int) -> str:
    """1-based column number -> A1 letters."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _as_date(cell) -> Optional[dt.date]:
    """A row-1 header cell (read UNFORMATTED) -> the week-ending date."""
    if isinstance(cell, bool) or not isinstance(cell, (int, float)):
        return None
    if cell < 40000 or cell > 60000:      # not a plausible date serial
        return None
    return EPOCH + dt.timedelta(days=int(cell))


@dataclass
class TabModel:
    title: str
    sheet_id: int
    gp_row: int                                   # 1-based
    weeks: Dict[dt.date, int] = field(default_factory=dict)   # sunday -> col
    values: Dict[dt.date, object] = field(default_factory=dict)
    block_col: Optional[int] = None               # first col of the right block
    last_label_row: int = 1                       # last row carrying a col-A label
    rows_read: int = 0

    @property
    def key(self) -> str:
        return names.key(self.title)

    @property
    def last_week(self) -> Optional[dt.date]:
        return max(self.weeks) if self.weeks else None

    @property
    def last_col(self) -> int:
        return max(self.weeks.values()) if self.weeks else 1

    def cell(self, sunday: dt.date) -> Optional[str]:
        col = self.weeks.get(sunday)
        return None if col is None else f"{a1_col(col)}{self.gp_row}"

    def is_filled(self, sunday: dt.date) -> bool:
        v = self.values.get(sunday)
        return v is not None and str(v).strip() != ""


def is_template(title: str) -> bool:
    return TEMPLATE_MARKER in title.lower()


def load_tabs(spreadsheet, read_cols: str = "BZ", read_rows: int = 60) -> List[TabModel]:
    """Model every rep tab in one batched read.

    One values_batch_get for the whole workbook rather than 65 worksheet reads —
    at 60 reads a minute the per-tab version trips the quota before it finishes.
    [[project_captainship-sheets-quota-kills-section1]]
    """
    from automations.recruiting_report.fill import _retry
    sheets = [ws for ws in spreadsheet.worksheets() if not is_template(ws.title)]
    ranges = [f"'{ws.title}'!A1:{read_cols}{read_rows}" for ws in sheets]
    res = _retry(spreadsheet.values_batch_get, ranges,
                 params={"valueRenderOption": "UNFORMATTED_VALUE",
                         "dateTimeRenderOption": "SERIAL_NUMBER"})

    out: List[TabModel] = []
    for ws, vr in zip(sheets, res["valueRanges"]):
        grid = vr.get("values", [])
        if not grid:
            continue
        width = max(len(r) for r in grid)
        grid = [list(r) + [""] * (width - len(r)) for r in grid]

        gp_row = next((i + 1 for i, r in enumerate(grid)
                       if str(r[0]).strip().lower() == GP_LABEL), None)
        if gp_row is None:
            continue                       # not a rep tab (or a renamed label)

        weeks, values = {}, {}
        for j in range(1, width):
            d = _as_date(grid[0][j])
            if d is None:
                continue
            weeks[d] = j + 1
            values[d] = grid[gp_row - 1][j] if j < len(grid[gp_row - 1]) else ""

        # The right-hand expenses block: the first column past the week run
        # that carries anything at all. Everything between is free space the
        # week run may grow into.
        block_col = None
        if weeks:
            for j in range(max(weeks.values()), width):
                if any(str(r[j]).strip() for r in grid if j < len(r)):
                    block_col = j + 1
                    break

        # The rep-facing rows are the ones with a label in col A ('Sales',
        # 'Goal', ... 'Professional Dress?'). Everything past that is empty
        # padding. A clone has to be blanked across exactly this band.
        last_label_row = max((i + 1 for i, r in enumerate(grid)
                              if str(r[0]).strip()), default=1)

        out.append(TabModel(title=ws.title, sheet_id=ws.id, gp_row=gp_row,
                            weeks=weeks, values=values, block_col=block_col,
                            last_label_row=last_label_row, rows_read=len(grid)))
    return out


def index_by_key(tabs: List[TabModel]) -> tuple:
    """({join key: TabModel}, [duplicate groups]).

    Two tabs can name the same person — 'Mustafa Alzaidy' and 'Mustafa Alzaidy '
    (trailing space) both exist. The one whose week run reaches furthest wins,
    because that's the one still being kept up; the loser is reported and never
    written to, so a number can't land on the copy nobody reads.
    """
    groups: Dict[str, List[TabModel]] = {}
    for t in tabs:
        groups.setdefault(t.key, []).append(t)
    index, dupes = {}, []
    for k, group in groups.items():
        if len(group) > 1:
            group = sorted(group,
                           key=lambda t: (t.last_week or dt.date.min, t.title),
                           reverse=True)
            dupes.append(group)
        index[k] = group[0]
    return index, dupes


# ---------- growing a tab's week run ----------

@dataclass
class Extension:
    tab: TabModel
    new_weeks: List[dt.date]
    inserts: int                 # columns that must be INSERTED (no free space)
    first_new_col: int


def plan_extension(tab: TabModel, target: dt.date) -> Optional[Extension]:
    """What it takes for `tab` to have a column for `target`.

    Returns None when the tab already has the week, or when it's too far behind
    to grow sanely (caller reports that as skipped).
    """
    if target in tab.weeks or not tab.weeks:
        return None
    last = tab.last_week
    if target <= last:
        return None                       # a hole mid-run, not a missing tail
    gap = (target - last).days // 7
    if gap > MAX_EXTEND_WEEKS:
        return None
    new_weeks = [last + dt.timedelta(days=7 * i) for i in range(1, gap + 1)]
    first_new_col = tab.last_col + 1
    free = (tab.block_col - first_new_col) if tab.block_col else gap
    return Extension(tab=tab, new_weeks=new_weeks,
                     inserts=max(0, gap - max(0, free)),
                     first_new_col=first_new_col)


def extension_requests(ext: Extension) -> List[dict]:
    """batch_update requests that grow the run: insert columns if the tab has
    run out of free space, then write the '=<prev>+7' headers and give the new
    header/paycheck cells the same formats the existing ones carry."""
    reqs: List[dict] = []
    tab = ext.tab
    if ext.inserts:
        # Insert INSIDE the gap, immediately before the expenses block, so the
        # block's own formulas shift with it (they're relative) instead of the
        # week run overwriting them.
        at = (tab.block_col or ext.first_new_col) - 1
        reqs.append({"insertDimension": {
            "range": {"sheetId": tab.sheet_id, "dimension": "COLUMNS",
                      "startIndex": at, "endIndex": at + ext.inserts},
            "inheritFromBefore": True}})
    span = {"sheetId": tab.sheet_id,
            "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": ext.first_new_col - 1,
            "endColumnIndex": ext.first_new_col - 1 + len(ext.new_weeks)}
    reqs.append({"repeatCell": {
        "range": span,
        "cell": {"userEnteredFormat": {"numberFormat": DATE_FORMAT,
                                       "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
    reqs.append({"repeatCell": {
        "range": {**span, "startRowIndex": tab.gp_row - 1,
                  "endRowIndex": tab.gp_row},
        "cell": {"userEnteredFormat": {"numberFormat": CURRENCY_FORMAT,
                                       "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
    return reqs


def extension_header_values(ext: Extension) -> List[dict]:
    """The '=<prev>+7' header formulas, as values_batch_update entries."""
    out = []
    for i, _week in enumerate(ext.new_weeks):
        col = ext.first_new_col + i
        out.append({"range": f"'{ext.tab.title}'!{a1_col(col)}1",
                    "values": [[f"={a1_col(col - 1)}1+7"]]})
    return out
