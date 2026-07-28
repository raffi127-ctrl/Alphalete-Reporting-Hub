"""Write a rep's Due Diligence block into their ICD's tab.

Megan's DD log has one tab per ICD. We find the tab whose title matches the
requested ICD and APPEND the rep's block below whatever's already there — never
overwrite a filled cell, and never auto-create a tab (Megan makes those). If
there's no tab for the ICD yet, we say so instead of guessing.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from .pull import RepDD, TableDD, PERIODS
from . import config as C


def _we_header(d: dt.date) -> str:
    return f"WE {d.month}.{d.day:02d}"


def _avg_cell(v: Optional[float]) -> str:
    return "" if v is None else f"{v:g}"


def _int_cell(v) -> str:
    return "" if v is None else str(v)


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _table_rows(rep: str, t: TableDD, weeks: List[dt.date],
                avg8_label: str, avg4_label: str, sales_label: str) -> List[List[str]]:
    """Two header rows + one data row for one product side, matching the
    template's column order (weeks newest-first, left to right)."""
    week_headers = [_we_header(s) for s in weeks]
    label_row = (["Reps Names", avg8_label, avg4_label]
                 + ["" for _ in weeks]
                 + ["0-30 Day Cancel Rate", "30-60 Day Cancel Rate",
                    "0-30 Day Churn", "30 Day Churn", "60 Day Churn", "90 Day Churn",
                    "Start Date or First Day of sales"])
    subhead_row = (["", "", sales_label] + week_headers
                   + ["", "", "", "", "", "", ""])
    data_row = ([rep, _avg_cell(t.avg_8wk), _avg_cell(t.avg_recent)]
                + [_int_cell(t.weekly.get(s)) for s in weeks]
                + [t.cancel_0_30, t.cancel_30_60]
                + [t.churn.get(p, "") for p in PERIODS]
                + [""])   # start date filled manually
    return [label_row, subhead_row, data_row]


def build_block(dd: RepDD, *, stamp: Optional[dt.date] = None) -> List[List[str]]:
    stamp = stamp or dt.date.today()
    title = [f"{dd.matched_rep or dd.rep} — pulled {stamp.isoformat()}"]
    ni = _table_rows(dd.matched_rep or dd.rep, dd.new_int, dd.weeks,
                     "8 WK New INT Average", "4 Week New INT Average", "New INT Sales")
    wl = _table_rows(dd.matched_rep or dd.rep, dd.wireless, dd.weeks,
                     "8 WK NL Average", "4 Week NL Average", "Wireless Sales")
    return [title, []] + ni + [[]] + wl


def target_tab_name(dd: RepDD) -> str:
    return C.DD_TAB_OVERRIDE or dd.icd or dd.owner


# --- team template (leader + N reps + total), matching Eve's DD layout --------
_CANCEL_CHURN = ["0-30 Day Cancel Rate", "30-60 Day Cancel Rate",
                 "0-30 Day Churn", "30 Day Churn", "60 Day Churn", "90 Day Churn",
                 "Start Date or First Day of sales"]


def _team_table(people: List[RepDD], weeks_old2new: List[dt.date], side: str) -> List[List[str]]:
    """One product table (side='ni' or 'wl'): 2 header rows + one row per person
    + a Total row. Weeks left-to-right oldest->newest, matching the VA layout."""
    if side == "ni":
        avg8, avg4, sales = "8 WK New INT Average", "4 Week New INT Average", "New INT Sales"
        tbl = lambda p: p.new_int   # noqa: E731
    else:
        avg8, avg4, sales = "8 WK NL Average", "4 Week NL Average", "Wireless Sales"
        tbl = lambda p: p.wireless  # noqa: E731
    week_hdrs = [f"WE {s.month}.{s.day:02d}" for s in weeks_old2new]
    label_row = ["Reps Names", avg8, avg4, sales] + [""] * 7 + _CANCEL_CHURN
    week_row = ["", "", ""] + week_hdrs + [""] * 7
    rows = [label_row, week_row]
    wk_sum = [0] * len(weeks_old2new)
    a8_sum = a4_sum = 0.0
    for p in people:
        t = tbl(p)
        wk = [t.weekly.get(s) for s in weeks_old2new]
        rows.append(
            [p.matched_rep or p.rep, _avg_cell(t.avg_8wk), _avg_cell(t.avg_recent)]
            + [_int_cell(v) for v in wk]
            + [t.cancel_0_30, t.cancel_30_60]
            + [t.churn.get(pp, "") for pp in PERIODS]
            + [p.start_date])
        for i, v in enumerate(wk):
            wk_sum[i] += int(v or 0)
        a8_sum += t.avg_8wk or 0
        a4_sum += t.avg_recent or 0
    rows.append(["Total", f"{a8_sum:g}", f"{a4_sum:g}"]
                + [str(v) for v in wk_sum] + [""] * 7)
    return rows


def build_team_block(people: List[RepDD], *, leader: str = "",
                     stamp: Optional[dt.date] = None) -> List[List[str]]:
    stamp = stamp or dt.date.today()
    weeks_old2new = list(reversed(people[0].weeks)) if people else []
    title = [f"{leader or (people[0].matched_rep if people else '')} — Team Due "
             f"Diligence — pulled {stamp.isoformat()}"]
    ni = _team_table(people, weeks_old2new, "ni")
    wl = _team_table(people, weeks_old2new, "wl")
    return [title, []] + ni + [[]] + wl


def write_team_block(people: List[RepDD], *, icd: str, leader: str = "",
                     dry_run: bool = True, stamp: Optional[dt.date] = None) -> dict:
    """Write a whole team (leader + reps + Total) into the ICD tab, in the DD
    template layout. Rows scale to the team size (Megan: add/remove rep rows to
    match the count). Creates the tab if it's new."""
    block = build_team_block(people, leader=leader, stamp=stamp)
    if dry_run:
        return {"dry_run": True, "sheet_id": C.DD_SHEET_ID, "tab": icd, "rows": block}

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(C.DD_SHEET_ID)
    ncols = max((len(r) for r in block), default=1)
    ws = _find_icd_ws(sh, icd)
    created = False
    if ws is None:
        ws = _retry(sh.add_worksheet, title=icd[:99], rows=max(len(block) + 20, 60),
                    cols=max(ncols, 20))
        created = True
    values = _retry(ws.get_all_values)
    last = 0
    for i in range(len(values), 0, -1):
        if any(str(c).strip() for c in values[i - 1]):
            last = i
            break
    start = 1 if last == 0 else last + 3
    rng = f"A{start}:{_col_letter(ncols)}{start + len(block) - 1}"
    padded = [r + [""] * (ncols - len(r)) for r in block]
    _retry(ws.update, rng, padded, value_input_option="USER_ENTERED")
    return {"dry_run": False, "wrote": True, "tab": ws.title, "range": rng,
            "rows_written": len(block), "created_tab": created}


def _find_icd_ws(sh, icd_name: str):
    """The worksheet whose title matches the ICD (exact-normalized, else the
    closest contains-match). None if nothing matches."""
    want = _norm(icd_name)
    if not want:
        return None
    tabs = sh.worksheets()
    for ws in tabs:                       # exact
        if _norm(ws.title) == want:
            return ws
    for ws in tabs:                       # ICD name contained in the tab title
        if want in _norm(ws.title) or _norm(ws.title) in want:
            return ws
    return None


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_rep_block(dd: RepDD, *, dry_run: bool = True,
                    stamp: Optional[dt.date] = None) -> dict:
    """Append the rep's DD block to their ICD tab. dry_run returns the exact
    block + target tab WITHOUT writing (default), for preview."""
    block = build_block(dd, stamp=stamp)
    tab = target_tab_name(dd)
    if dry_run:
        return {"dry_run": True, "sheet_id": C.DD_SHEET_ID, "tab": tab,
                "rows": block, "note": "no write (preview)"}

    if not tab:
        return {"dry_run": False, "wrote": False,
                "error": "no ICD given — can't pick a tab"}

    # gspread only on the live-write path.
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(C.DD_SHEET_ID)
    ncols = max((len(r) for r in block), default=1)
    ws = _find_icd_ws(sh, tab)
    created = False
    if ws is None:
        # No tab for this ICD yet — create one (Megan: "create the ICD tabs as
        # they are requested"). A new tab only adds; it never touches existing
        # data, so this is safe.
        ws = _retry(sh.add_worksheet, title=tab[:99], rows=200, cols=max(ncols, 20))
        created = True

    values = _retry(ws.get_all_values)
    last = 0
    for i in range(len(values), 0, -1):
        if any(str(c).strip() for c in values[i - 1]):
            last = i
            break
    start = 1 if last == 0 else last + 3    # top of a fresh tab; else a 2-row gap
    rng = f"A{start}:{_col_letter(ncols)}{start + len(block) - 1}"
    padded = [r + [""] * (ncols - len(r)) for r in block]
    _retry(ws.update, rng, padded, value_input_option="USER_ENTERED")
    return {"dry_run": False, "wrote": True, "tab": ws.title, "range": rng,
            "rows_written": len(block), "created_tab": created}
