"""Write the NDS activation rates: a history log + one readable tab per captain.

WORKBOOK  "Captainship Metrics Report - Cancel/Activation Rate" (the one that
          already holds the Fiber 'Activation Rate - <captain>' tabs). While
          building, the SANDBOX copy of it — see SHEET_IDS.

LOG TAB   'NDS Activation Log' — one row per (day, captain, owner, rep):
              Date | Captain | Owner | Rep | 10-19 | 20-29 | 30-60
          Owner '(Captainship)' = the captainship average; Rep 'Total' = the
          owner's own number. This is the record. Append-only, except a re-run
          of the same day replaces that day's rows for that captain.

CAPTAIN TABS  'Activation Rate - <Captain> (NDS)' — REDRAWN from the log on
          every run (values and formatting), so no row ever has to be inserted
          by hand when a rep appears and nothing drifts. Three boxes
          (10-19 / 20-29 / 30-60). In each: Captainship Avg, then every owner
          (grey row, their total) with their reps underneath. Newest day in
          column C, older days to the right. A rep shows up in a box only if
          they have a number in that window on one of the days shown.
          These tabs are built by this report and nobody types in them.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.new_internet_churn import fill as _shared
from automations.nds_activation_rate.pull import WINDOWS

SHEET_IDS = {
    "real": "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E",
    "sandbox": "1Je8W3Pv5sQ1GurNQeExBQBimzgDjN5gAxJq2o7P17-M",
}
LOG_TAB = "NDS Activation Log"
LOG_HEADER = ["Date", "Captain", "Owner", "Rep"] + [k for k, _ in WINDOWS]
CAPTAINSHIP = "(Captainship)"
DAYS_SHOWN = 30

ORANGE = {"red": 0.902, "green": 0.569, "blue": 0.220}
PINK = {"red": 0.918, "green": 0.820, "blue": 0.863}
GREY = {"red": 0.937, "green": 0.937, "blue": 0.937}
WHITE = {"red": 1, "green": 1, "blue": 1}


def tab_name(captain: str) -> str:
    return f"Activation Rate - {captain} (NDS)"


def open_book(sandbox: bool):
    return _shared.open_by_key(SHEET_IDS["sandbox" if sandbox else "real"])


def _ws(book, title: str, rows: int = 200, cols: int = 40):
    try:
        return book.worksheet(title)
    except Exception:  # noqa: BLE001 — WorksheetNotFound
        return book.add_worksheet(title=title, rows=rows, cols=cols)


# ---------------------------------------------------------------- the log --

def log_rows(day: dt.date, captain: str, data: Dict) -> List[List[str]]:
    d = day.isoformat()
    out = [[d, captain, CAPTAINSHIP, "Total"]
           + [data["avg"].get(k, "") for k, _ in WINDOWS]]
    for owner, o in data["owners"].items():
        out.append([d, captain, owner, "Total"]
                   + [o["total"].get(k, "") for k, _ in WINDOWS])
        for rep, vals in o["reps"].items():
            if not any(vals.get(k) for k, _ in WINDOWS):
                continue        # a rep with no number anywhere is noise
            out.append([d, captain, owner, rep]
                       + [vals.get(k, "") for k, _ in WINDOWS])
    return out


def write_log(book, day: dt.date, captain: str, new_rows, *, logfn=print):
    """Append today's rows; if this captain already has rows for today
    (a re-run), rewrite the log without them first."""
    ws = _ws(book, LOG_TAB, rows=1000, cols=len(LOG_HEADER))
    grid = _shared._retry(ws.get_all_values)
    if not grid or grid[0][:len(LOG_HEADER)] != LOG_HEADER:
        if grid and any(any(c for c in r) for r in grid):
            raise RuntimeError(f"'{LOG_TAB}' has an unexpected header "
                               f"{grid[0][:8]} — not touching it")
        ws.update(values=[LOG_HEADER], range_name="A1")
        grid = [LOG_HEADER]
    d = day.isoformat()
    body = grid[1:]
    keep = [r for r in body if not (r[0] == d and r[1] == captain)]
    if len(keep) != len(body):
        logfn(f"  log: replacing {len(body) - len(keep)} row(s) of {d} {captain}")
        all_rows = [LOG_HEADER] + keep + new_rows
        if ws.row_count < len(all_rows) + 10:
            ws.add_rows(len(all_rows) + 500 - ws.row_count)
        ws.batch_clear([f"A2:{_col_letter(len(LOG_HEADER))}{ws.row_count}"])
        ws.update(values=all_rows, range_name="A1",
                  value_input_option="RAW")
    else:
        ws.append_rows(new_rows, value_input_option="RAW")
    logfn(f"  log: {len(new_rows)} row(s) for {d} {captain}")
    return [LOG_HEADER] + keep + new_rows


def history(grid, captain: str):
    """-> (days newest first, {(owner, rep): {day: {win: pct}}}, owner order)"""
    vals: Dict = {}
    days = set()
    owner_order: List[str] = []
    for r in grid[1:]:
        if len(r) < 4 or r[1] != captain:
            continue
        day, owner, rep = r[0], r[2], r[3]
        days.add(day)
        if owner != CAPTAINSHIP and owner not in owner_order:
            owner_order.append(owner)
        wins = {k: (r[4 + i] if len(r) > 4 + i else "")
                for i, (k, _) in enumerate(WINDOWS)}
        vals.setdefault((owner, rep), {})[day] = wins
    ordered = sorted(days, reverse=True)[:DAYS_SHOWN]
    return ordered, vals, owner_order


# ------------------------------------------------------- the captain tab --

def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _label(day_iso: str) -> str:
    d = dt.date.fromisoformat(day_iso)
    return f"{d.strftime('%a')} {d.month}/{d.day}/{d.strftime('%y')}"


def render(captain: str, captain_full: str, grid, today_owners: List[str]):
    """Build the tab as rows of values + a list of (row, kind) for styling."""
    days, vals, owner_order = history(grid, captain)
    # Today's roster first (Tableau's order), then owners only in history.
    owners = list(today_owners) + [o for o in owner_order
                                   if o not in today_owners]
    rows: List[List[str]] = [[captain_full.upper() + " - NDS ACTIVATION BY REP"]]
    kinds: List = [(1, "title")]

    def cells(key, win):
        per_day = vals.get(key, {})
        return [per_day.get(d, {}).get(win, "") for d in days]

    for win, _hdr in WINDOWS:
        rows.append([])
        rows.append([f"ACTIVATION {win} DAYS", "Rep"] + [_label(d) for d in days])
        kinds.append((len(rows), "box"))
        rows.append(["Captainship Avg", ""] + cells((CAPTAINSHIP, "Total"), win))
        kinds.append((len(rows), "avg"))
        for owner in owners:
            rows.append([owner, "Owner total"] + cells((owner, "Total"), win))
            kinds.append((len(rows), "owner"))
            reps = sorted({rep for (o, rep) in vals if o == owner and rep != "Total"
                           and any(cells((o, rep), win))})
            for rep in reps:
                rows.append(["", rep] + cells((owner, rep), win))
    return rows, kinds, len(days)


def write_tab(book, captain: str, rows, kinds, n_days: int, *, logfn=print):
    title = tab_name(captain)
    width = 2 + max(n_days, 1)
    ws = _ws(book, title, rows=max(200, len(rows) + 50), cols=max(40, width + 5))
    if ws.row_count < len(rows) + 10:
        ws.add_rows(len(rows) + 50 - ws.row_count)
    if ws.col_count < width + 2:
        ws.add_cols(width + 5 - ws.col_count)
    sid = ws.id
    full = {"sheetId": sid, "startRowIndex": 0, "endRowIndex": ws.row_count,
            "startColumnIndex": 0, "endColumnIndex": ws.col_count}
    # Wipe values AND formats: the tab is fully redrawn every run.
    book.batch_update({"requests": [{"updateCells": {
        "range": full, "fields": "userEnteredValue,userEnteredFormat"}}]})
    padded = [r + [""] * (width - len(r)) for r in rows]
    ws.update(values=padded, range_name="A1", value_input_option="USER_ENTERED")

    def rng(r, c0=0, c1=None):
        return {"sheetId": sid, "startRowIndex": r - 1, "endRowIndex": r,
                "startColumnIndex": c0, "endColumnIndex": c1 or width}

    def fmt(r, bg=None, bold=False, fg=None, size=11, c0=0, c1=None):
        f = {"textFormat": {"bold": bold, "fontSize": size},
             "horizontalAlignment": "CENTER"}
        if fg:
            f["textFormat"]["foregroundColor"] = fg
        if bg:
            f["backgroundColor"] = bg
        return {"repeatCell": {"range": rng(r, c0, c1), "cell": {
            "userEnteredFormat": f},
            "fields": "userEnteredFormat(backgroundColor,textFormat,"
                      "horizontalAlignment)"}}

    reqs = [
        # numbers as 0.0% everywhere in the day columns
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1,
                                  "endRowIndex": len(rows),
                                  "startColumnIndex": 2, "endColumnIndex": width},
                        "cell": {"userEnteredFormat": {
                            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
                            "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}},
        {"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 2},
            "properties": {"pixelSize": 190}, "fields": "pixelSize"}},
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenColumnCount": 2}},
            "fields": "gridProperties.frozenColumnCount"}},
    ]
    for r, kind in kinds:
        if kind == "title":
            reqs.append(fmt(r, bold=True, size=13, c1=1))
        elif kind == "box":
            reqs.append(fmt(r, bg=ORANGE, bold=True, size=12))
        elif kind == "avg":
            reqs.append(fmt(r, bg=PINK, bold=True, size=12))
        elif kind == "owner":
            reqs.append(fmt(r, bg=GREY, bold=True))
    book.batch_update({"requests": reqs})
    logfn(f"  tab '{title}': {len(rows)} row(s), {n_days} day column(s)")
    return title
