"""Fill + weekly roll of the 'Country Campaign Board' tab (layout.py builds it).

Input everywhere is the same shape: {campaign: {date: units}} with COUNTRY
totals per day (credico_pdf for Fios/Frontier, the Tableau pull for the AT&T
campaigns). A campaign missing from the input is left untouched; a day with no
number stays BLANK, never 0.

The board's week is Monday..Sunday; C3 holds its Week Ending date. It rolls when
YESTERDAY falls in a newer week — i.e. Tuesday, like the ORG board: Monday's run
still writes Sunday into the closing week. C3, not the calendar, decides, so a
missed day just rolls on the next run.

Rolling = add the closed week to the hidden data tab (one row per campaign + an
'All Campaigns' row, at row 2 under its header) as VALUES, blank the
campaign x day cells and move C3. The per-campaign boxes read the history with
SUMIFS on C3, so they re-point by themselves. Rows are found by their col-B
label every run, never by index.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.program_daily_summary import layout as L

Data = Dict[str, Dict[dt.date, int]]


def week_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def target_monday(today: dt.date) -> dt.date:
    """The week the run fills: the one holding YESTERDAY (Mon fills Sunday)."""
    return week_monday(today - dt.timedelta(days=1))


def parse_we(v) -> Optional[dt.date]:
    """C3 read UNFORMATTED: a Sheets serial number (or '' when unset)."""
    if isinstance(v, (int, float)) and v > 0:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    return None


def locate(col_b: List[str]) -> dict:
    """Row numbers (1-based) by label from column B's values."""
    rows = {"campaigns": {}}
    for i, v in enumerate(col_b, start=1):
        v = (v or "").strip()
        if v == L.WE_LABEL and "we" not in rows:
            rows["we"] = i
        elif v == L.PS_BAR and "bar" not in rows:
            rows["bar"] = i
        elif "bar" in rows and "total" not in rows:
            if v in L.CAMPAIGNS:
                rows["campaigns"][v] = i
            elif v == "Grand Total":
                rows["total"] = i
    missing = [k for k in ("we", "bar", "total") if k not in rows]
    missing += [c for c in L.CAMPAIGNS if c not in rows["campaigns"]]
    if missing:
        raise RuntimeError(f"'{L.TAB}': can't find {missing} in column B")
    return rows


def day_cells(monday: dt.date, data: Data, today: dt.date) -> Dict[str, list]:
    """{campaign: [Mon..Sun]} for one week: a number, or '' for a day not
    reported (or not over yet). Campaigns with no data at all are omitted."""
    out = {}
    for camp in L.CAMPAIGNS:
        days = data.get(camp) or {}
        if not days:
            continue
        row = []
        for k in range(7):
            d = monday + dt.timedelta(days=k)
            row.append(days[d] if (d < today and d in days) else "")
        out[camp] = row
    return out


def history_rows(monday: dt.date, cells: Dict[str, list]) -> List[list]:
    """The rows one closed week adds: 'All Campaigns' first, then each
    campaign — WE | campaign | Mon..Sun | Grand Total."""
    we = (monday + dt.timedelta(days=6)).strftime("%m/%d/%Y")
    out = []
    for camp in L.CAMPAIGNS:
        row = cells.get(camp, [""] * 7)
        vals = [v for v in row if v != ""]
        out.append([we, camp] + list(row) + [sum(vals) if vals else ""])
    complete = all(r[9] != "" for r in out)
    # a campaign with no numbers that week gets NO row: an empty row would
    # read as 0 in the boxes' SUMIFS ("Sales (Last Week) 0").
    out = [r for r in out if r[9] != ""]
    per_day = []
    for k in range(7):
        vals = [r[2 + k] for r in out if r[2 + k] != ""]
        per_day.append(sum(vals) if vals else "")
    tot = [r[9] for r in out]
    if not complete:
        # a campaign is missing that week: an 'All Campaigns' total would be
        # short and make next week's growth look fake -> no All row at all.
        return out
    return [[we, L.ALL] + per_day + [sum(tot)]] + out


def _read_week(ws, rows) -> Dict[str, list]:
    """The campaign x day block as it stands on the sheet (for freezing)."""
    first = min(rows["campaigns"].values())
    last = max(rows["campaigns"].values())
    grid = ws.get(f"B{first}:I{last}", value_render_option="UNFORMATTED_VALUE")
    out = {}
    for line in grid:
        line = list(line) + [""] * (8 - len(line))
        if line[0] in L.CAMPAIGNS:
            out[line[0]] = [v if isinstance(v, (int, float)) else "" for v in line[1:8]]
    return out


def _insert_history(data_ws, new: List[list]) -> None:
    """Newest week on top of the hidden data tab (row 2, under its header)."""
    # rows start in column A, the table starts in B -> pad one blank cell
    data_ws.insert_rows([[""] + row for row in new], row=2, value_input_option="USER_ENTERED",
                   inherit_from_before=False)


def _tab(ws=None):
    return ws or L.rfill.open_by_key(L.SHEET_ID).worksheet(L.TAB)


def _data_tab(ws=None):
    return ws or L.rfill.open_by_key(L.SHEET_ID).worksheet(L.DATA_TAB)


BACKUP_TAB = f"{L.TAB} (pre-rollover backup)"


def weeks_in_history(data_ws) -> set:
    """Week-ending dates already on the data tab (col B, unformatted)."""
    col = data_ws.col_values(2, value_render_option="UNFORMATTED_VALUE")[1:]
    return {d for d in (parse_we(v) for v in col) if d}


def snapshot(ws, *, dry_run: bool, logfn=print) -> None:
    """Copy the board to BACKUP_TAB (replacing the previous backup) before the
    roll touches it — same rule as the Country Sales Board. The data tab is
    insert-only, so it needs no backup."""
    if dry_run:
        logfn(f"  [dry-run] would snapshot -> {BACKUP_TAB!r}")
        return
    sh = ws.spreadsheet
    try:
        sh.del_worksheet(sh.worksheet(BACKUP_TAB))
    except Exception:  # noqa: BLE001 — no previous backup
        pass
    bk = sh.duplicate_sheet(ws.id, new_sheet_name=BACKUP_TAB)
    sh.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": bk.id, "hidden": True}, "fields": "hidden"}}]})
    logfn(f"  snapshot -> {BACKUP_TAB!r}")


def run(data: Data, *, today: Optional[dt.date] = None, dry_run: bool = False,
        enable_rollover: bool = False, logfn=print, ws=None, data_ws=None
        ) -> dt.date:
    """Roll (Tuesdays, if enabled) then fill. Returns the Monday it filled.

    Rules taken from the Country Sales Board's rollover:
      * the SHEET (C3) says which week is showing, not the calendar; Monday
        never rolls (it writes Sunday into the closing week); a missed Tuesday
        rolls on the next run;
      * snapshot before touching anything;
      * never the same week twice — if a crashed roll already put that week on
        the data tab, the insert is skipped and the roll just finishes;
      * the closed week is frozen with the freshest SOURCE numbers for it
        (Sunday lands late), falling back to what the board showed;
      * without enable_rollover a due roll is NOT done and the run keeps
        filling the week the board shows, so nothing lands in the wrong week.
    """
    today = today or dt.date.today()
    ws = _tab(ws)
    rows = locate(ws.col_values(2))
    shown_we = parse_we(ws.acell(f"C{rows['we']}",
                                 value_render_option="UNFORMATTED_VALUE").value)
    shown = shown_we - dt.timedelta(days=6) if shown_we else None
    want = target_monday(today)

    if shown and shown < want and not enable_rollover:
        logfn(f"roll due (board on WE {shown_we}) but --enable-rollover is off "
              f"— filling the week the board shows")
        want = shown
    elif shown and shown < want:
        logfn(f"roll: WE {shown_we} -> history, board -> WE "
              f"{want + dt.timedelta(days=6)}")
        snapshot(ws, dry_run=dry_run, logfn=logfn)
        frozen = _read_week(ws, rows)
        frozen.update(day_cells(shown, data, dt.date.max))
        new = history_rows(shown, frozen)
        logfn("  closed week: " + ", ".join(f"{r[1]} {r[9]}" for r in new))
        dws = _data_tab(data_ws)
        if shown_we in weeks_in_history(dws):
            logfn(f"  WE {shown_we} is already in the history (an earlier "
                  f"roll got that far) — not adding it again")
        elif not dry_run:
            _insert_history(dws, new)
        if not dry_run:
            ws.batch_clear([f"C{min(rows['campaigns'].values())}:"
                            f"I{max(rows['campaigns'].values())}"])
    if shown != want:
        we = want + dt.timedelta(days=6)
        logfn(f"board week -> WE {we}")
        if not dry_run:
            ws.update(f"C{rows['we']}", [[we.strftime("%m/%d/%Y")]],
                      value_input_option="USER_ENTERED")

    cells = day_cells(want, data, today)
    updates = [{"range": f"C{rows['campaigns'][c]}:I{rows['campaigns'][c]}",
                "values": [v]} for c, v in cells.items()]
    for c, v in cells.items():
        logfn(f"  {c:<10} {v}")
    skipped = [c for c in L.CAMPAIGNS if c not in cells]
    if skipped:
        logfn(f"  no data this run (left as is): {skipped}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    grow(ws, want, dry_run=dry_run, logfn=logfn, data_ws=data_ws)
    return want


def history_span(week_endings, shown_we: dt.date) -> int:
    """Columns the Weekly History needs: from last week back to the OLDEST
    stored week (column k = shown WE - 7*(k+1))."""
    old = [w for w in week_endings if w and w < shown_we]
    return max(((shown_we - min(old)).days // 7) if old else 0, 0)


def grow(ws, monday: dt.date, *, dry_run=False, logfn=print, data_ws=None):
    """Keep Weekly History wide enough for every stored week (layout.grow_history)."""
    grid = _data_tab(data_ws).get("B2:B", value_render_option="UNFORMATTED_VALUE")
    n = history_span([parse_we(r[0]) for r in grid if r],
                     monday + dt.timedelta(days=6))
    L.grow_history(ws, n, dry_run=dry_run, logfn=logfn)


def verify(ws, monday: dt.date, today: dt.date) -> List[str]:
    """Campaigns whose newest day (yesterday, or Sunday on a closing-week fill)
    is NOT a number on the board after the run. Empty list = all good. Same
    idea as the Country Sales Board's post-write check: a run that wrote
    nothing must not be recorded as done."""
    day = min(today - dt.timedelta(days=1), monday + dt.timedelta(days=6))
    col = L.DAYCOLS[(day - monday).days]
    rows = locate(ws.col_values(2))
    vals = ws.batch_get([f"{col}{rows['campaigns'][c]}" for c in L.CAMPAIGNS],
                        value_render_option="UNFORMATTED_VALUE")
    return [c for c, v in zip(L.CAMPAIGNS, vals)
            if not (v and v[0] and isinstance(v[0][0], (int, float)))]


def backfill_week(monday: dt.date, data: Data, *, dry_run: bool = False,
                  logfn=print, data_ws=None) -> None:
    """Add the campaigns a CLOSED week is still missing on the data tab,
    without touching (or duplicating) the ones already there. When that makes
    the week complete (all 5), its 'All Campaigns' row is added too, built
    from the stored rows + the new ones. Only full 7-day weeks are added."""
    data_ws = _data_tab(data_ws)
    we = monday + dt.timedelta(days=6)
    grid = data_ws.get("B2:K", value_render_option="UNFORMATTED_VALUE")
    have = {}
    for r in grid:
        r = list(r) + [""] * (10 - len(r))
        if parse_we(r[0]) == we:
            have[r[1]] = [v if isinstance(v, (int, float)) else "" for v in r[2:9]]
    new = {c: v for c, v in day_cells(monday, data, dt.date.max).items()
           if "" not in v and c not in have}
    if not new:
        logfn(f"  WE {we}: nothing new to add (have {sorted(have)})")
        return
    rows = [r for r in history_rows(monday, new) if r[1] != L.ALL]
    merged = {**{c: v for c, v in have.items() if c in L.CAMPAIGNS}, **new}
    if L.ALL not in have and all(c in merged for c in L.CAMPAIGNS):
        rows = [r for r in history_rows(monday, merged) if r[1] == L.ALL] + rows
    logfn(f"  WE {we}: adding " + ", ".join(f"{r[1]} {r[9]}" for r in rows))
    if not dry_run:
        _insert_history(data_ws, rows)


def seed_history(weeks: List[dt.date], data: Data, *, dry_run: bool = False,
                 logfn=print, data_ws=None) -> None:
    """Add closed weeks (their Mondays) to the history, newest ending on top.
    A campaign without all 7 days for a week is left blank in that week's row
    (and so out of 'All Campaigns') rather than counted short."""
    data_ws = _data_tab(data_ws)
    for monday in sorted(weeks):
        cells = {c: v for c, v in day_cells(monday, data, dt.date.max).items()
                 if "" not in v}
        new = history_rows(monday, cells)
        logfn(f"  WE {monday + dt.timedelta(days=6)}: "
              + ", ".join(f"{r[1]} {r[9]}" for r in new))
        if not dry_run:
            _insert_history(data_ws, new)
