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


def _hex(h: str) -> dict:
    h = h.lstrip("#")
    return {k: int(h[i:i + 2], 16) / 255 for k, i in
            (("red", 0), ("green", 2), ("blue", 4))}


# One colour family per bucket so the three boxes read apart at a glance
# (Eve 2026-11-10: "una división de colores, alternados"). header = the box
# title row (white text), avg = Captainship Avg, owner = each owner's total
# row, band = the tint behind every other owner's reps.
#
# 11/10 second pass — Eve: "muy desabrido… los colores están muy blancos".
# So: deep header, solid owner rows with WHITE text, a clearly visible band
# (not a near-white tint), and the numbers themselves heat-coloured.
PALETTE = {
    "10-19": {"header": _hex("#0B3D91"), "avg": _hex("#1C5FD0"),
              "owner": _hex("#3D85E8"), "band": _hex("#BCD4F6")},
    "20-29": {"header": _hex("#1B5E20"), "avg": _hex("#2E7D32"),
              "owner": _hex("#43A047"), "band": _hex("#C3E6C5")},
    "30-60": {"header": _hex("#8A3B00"), "avg": _hex("#C25E00"),
              "owner": _hex("#EF8A17"), "band": _hex("#FBD3A6")},
}
# Heat scale on every % cell: red low, yellow middle, green high.
HEAT = (("NUMBER", "0.5", _hex("#E06666")),
        ("NUMBER", "0.75", _hex("#FFD966")),
        ("NUMBER", "0.9", _hex("#57BB8A")))


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
    kinds: List = [(1, "title", "", -1)]

    def cells(key, win):
        per_day = vals.get(key, {})
        return [per_day.get(d, {}).get(win, "") for d in days]

    # kinds: (row, kind, window, owner index) — window/owner index drive the
    # per-bucket colour and the alternating owner bands in write_tab.
    for win, _hdr in WINDOWS:
        rows.append([])
        rows.append([f"ACTIVATION {win} DAYS", "Rep"] + [_label(d) for d in days])
        kinds.append((len(rows), "box", win, -1))
        rows.append(["Captainship Avg", ""] + cells((CAPTAINSHIP, "Total"), win))
        kinds.append((len(rows), "avg", win, -1))
        for i, owner in enumerate(owners):
            rows.append([owner, "Owner total"] + cells((owner, "Total"), win))
            kinds.append((len(rows), "owner", win, i))
            reps = {rep for (o, rep) in vals if o == owner and rep != "Total"
                    and any(cells((o, rep), win))}
            # Best first, on the newest day that has a number (Eve: a flat
            # alphabetical list is a wall of names; ranked, it reads).
            def _key(rep, _o=owner, _w=win):
                c = [x for x in cells((_o, rep), _w) if x]
                try:
                    return (-float(c[0].rstrip("%")), rep) if c else (1.0, rep)
                except ValueError:
                    return (1.0, rep)
            for rep in sorted(reps, key=_key):
                rows.append(["", "   " + rep] + cells((owner, rep), win))
                kinds.append((len(rows), "rep", win, i))
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
        # frozen names; the group '+' sits on the OWNER row above its reps
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenColumnCount": 2,
                                               "rowGroupControlAfter": False}},
            "fields": "gridProperties.frozenColumnCount,"
                      "gridProperties.rowGroupControlAfter"}},
    ]
    edge = {"style": "SOLID_MEDIUM", "color": {"red": 0.2, "green": 0.2, "blue": 0.2}}
    # Clear what a redraw would otherwise stack up: old row groups and old
    # conditional-format rules (updateCells above wipes neither).
    meta = book.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,"
                                                "rowGroups,conditionalFormats)"})
    me = next((s for s in meta.get("sheets", [])
               if s.get("properties", {}).get("sheetId") == sid), {})
    pre = []
    for g in sorted(me.get("rowGroups", []), key=lambda g: -g.get("depth", 1)):
        pre.append({"deleteDimensionGroup": {"range": g["range"]}})
    for _ in me.get("conditionalFormats", []):
        pre.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    if pre:
        book.batch_update({"requests": pre})

    # Box extents (avg row .. last rep row) for the heat scale, and each
    # owner's rep rows for the collapsible groups.
    box_rows: dict = {}
    rep_runs: list = []
    run = None
    for r, kind, win, idx in kinds:
        if kind in ("avg", "owner", "rep"):
            lo, hi = box_rows.get(win, (r, r))
            box_rows[win] = (min(lo, r), max(hi, r))
        if kind == "rep":
            if run and run[2] == (win, idx) and run[1] == r - 1:
                run[1] = r
            else:
                run = [r, r, (win, idx)]
                rep_runs.append(run)
    for win, (lo, hi) in box_rows.items():
        pts = {}
        for name, (typ, val, color) in zip(("minpoint", "midpoint", "maxpoint"), HEAT):
            pts[name] = {"type": typ, "value": val, "color": color}
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": sid, "startRowIndex": lo - 1, "endRowIndex": hi,
                        "startColumnIndex": 2, "endColumnIndex": width}],
            "gradientRule": pts}}})

    for r, kind, win, idx in kinds:
        pal = PALETTE.get(win, {})
        if kind == "title":
            reqs.append(fmt(r, bold=True, size=14, c1=1))
        elif kind == "box":
            reqs.append(fmt(r, bg=pal["header"], bold=True, size=13, fg=WHITE))
            # The day labels parse as dates — show them as dates, not as the
            # 0.0% the day columns carry (11/10 first draw read '4633600.0%').
            reqs.append({"repeatCell": {"range": rng(r, 2, width), "cell": {
                "userEnteredFormat": {"numberFormat": {
                    "type": "DATE", "pattern": "ddd m/d/yy"}}},
                "fields": "userEnteredFormat.numberFormat"}})
        elif kind == "avg":
            reqs.append(fmt(r, bg=pal["avg"], bold=True, size=12, fg=WHITE))
        elif kind == "owner":
            reqs.append(fmt(r, bg=pal["owner"], bold=True, size=11, fg=WHITE))
            reqs.append({"updateBorders": {"range": rng(r), "top": edge,
                                           "bottom": edge}})
        elif kind == "rep":
            # owners alternate: coloured band, white band, coloured band...
            reqs.append(fmt(r, bg=pal["band"] if idx % 2 == 0 else WHITE))
    # Reps fold under their owner: the tab opens as a short list of owners,
    # '+' on the left opens one owner's team.
    for lo, hi, _k in rep_runs:
        g = {"sheetId": sid, "dimension": "ROWS", "startIndex": lo - 1,
             "endIndex": hi}
        reqs.append({"addDimensionGroup": {"range": g}})
    for lo, hi, _k in rep_runs:
        reqs.append({"updateDimensionGroup": {"dimensionGroup": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": lo - 1, "endIndex": hi},
            "depth": 1, "collapsed": True}, "fields": "collapsed"}})
    # Names read left-to-right; long rep names were clipped when centred.
    reqs.append({"repeatCell": {"range": {
        "sheetId": sid, "startRowIndex": 0, "endRowIndex": len(rows),
        "startColumnIndex": 0, "endColumnIndex": 2},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
        "fields": "userEnteredFormat.horizontalAlignment"}})
    for c0, px in ((0, 215), (1, 250), (2, 110)):
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": c0,
            "endIndex": c0 + 1 if c0 < 2 else width},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    book.batch_update({"requests": reqs})
    logfn(f"  tab '{title}': {len(rows)} row(s), {n_days} day column(s)")
    return title
