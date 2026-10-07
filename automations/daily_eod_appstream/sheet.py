"""The 'Daily EOD AppStream' tab of ARS Management 2.0 — the email's numbers, kept.

Eve 2026-10-07: "se debe guardar en una sheet ... en la misma ruta en que hacemos
los '1st to 2nd Below the Mark' y 'Call List to 2nd Round' pero en una tab
separada". Same workbook, OUR OWN tab — Perli's hand-filled 'EOD Report
ApplicantStream' tab is never touched.

Shape copies Perli's tab: one block per week, NEWEST ON TOP, each block
    DAILY EOD APPSTREAM                                   (title)
    (blank) | Monday 10/5 | ... | Saturday 10/10 | WEEKLY TOTALS   (8 cols each)
    Mon 10/5 – Sat 10/10 | 1st B | 1st S | % | B to 2nd | % | 2nd B | 2nd S | %  ...
    one row per office, alphabetical
    TOTAL
    (spacer)
Saturday is a column because Monday's email reports it (Perli's stops at Friday).
Days not reached yet are blank, never #DIV/0!.

Every run REWRITES the current week's block (found by its label in col A, never
by a row number) — the days accumulate and a late AppStream edit to an earlier
day lands. Past weeks are left exactly as they were.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

SHEET_ID = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"   # ARS Management 2.0
TAB = "Daily EOD AppStream"
TITLE = "DAILY EOD APPSTREAM"
HEADS = ["1st B", "1st S", "%", "B to 2nd", "%", "2nd B", "2nd S", "%"]
PCT_OFFSETS = (2, 4, 7)            # the three % columns inside each 8-col group
N_GROUPS = 7                       # Mon..Sat + WEEKLY TOTALS
N_COLS = 1 + 8 * N_GROUPS

CYAN = {"red": 0.0, "green": 1.0, "blue": 1.0}
GREY = {"red": 0.85, "green": 0.85, "blue": 0.85}
LIGHT = {"red": 0.95, "green": 0.95, "blue": 0.95}
GREEN = {"red": 0.341, "green": 0.733, "blue": 0.541}     # #57bb8a, as in the email
RED = {"red": 0.878, "green": 0.4, "blue": 0.4}           # #e06666
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def week_label(monday: dt.date) -> str:
    sat = monday + dt.timedelta(days=5)
    return f"Mon {monday.month}/{monday.day} – Sat {sat.month}/{sat.day}"


def _group(r: Optional[Dict[str, int]], pct, whole_pct) -> List:
    """8 cells for one day; all blank when the day has not happened yet."""
    if r is None:
        return [""] * 8
    p1, pb, p2 = pct(r["s1"], r["b1"]), pct(r["b2nd"], r["s1"]), pct(r["s2"], r["b2"])
    return [r["b1"], r["s1"], "" if p1 is None else p1,
            r["b2nd"], "" if pb is None else pb,
            r["b2"], r["s2"], "" if p2 is None else p2]


def build_block(monday: dt.date, days: List[Optional[Dict[str, Dict[str, int]]]],
                week: Dict[str, Dict[str, int]], *, pct, whole_pct, sum_rows
                ) -> Tuple[List[List], List[Tuple[int, int, Optional[float]]]]:
    """(rows, [(row offset, col, 2nd-round %)]) for one week.

    days: 6 entries, Monday..Saturday, each {owner: row} or None (not reached)."""
    day_row = [""]
    for i in range(6):
        d = monday + dt.timedelta(days=i)
        day_row += [f"{d:%A} {d.month}/{d.day}"] + [""] * 7
    day_row += ["WEEKLY TOTALS"] + [""] * 7
    rows = [[TITLE] + [""] * (N_COLS - 1), day_row,
            [week_label(monday)] + HEADS * N_GROUPS]
    owners = sorted(week, key=str.lower)
    for owner in owners + ["TOTAL"]:
        line = [owner]
        for d in days:
            if d is None:
                line += _group(None, pct, whole_pct)
            elif owner == "TOTAL":
                line += _group(sum_rows(list(d.values())), pct, whole_pct)
            else:
                line += _group(d.get(owner), pct, whole_pct)
        tot = sum_rows(list(week.values())) if owner == "TOTAL" else week[owner]
        line += _group(tot, pct, whole_pct)
        rows.append(line)
    rows.append([""] * N_COLS)                              # spacer

    colors = []
    for off, line in enumerate(rows[3:-1], start=3):
        for g in range(N_GROUPS):
            c = 1 + 8 * g + 7
            v = line[c]
            colors.append((off, c, None if v == "" else v))
    return rows, colors


def find_block(col_a: List[str], label: str) -> Optional[Tuple[int, int]]:
    """(first row, last row), 1-based, of the block whose header says `label`."""
    for i, v in enumerate(col_a):
        if v.strip() == label and i >= 2 and col_a[i - 2].strip() == TITLE:
            start = i - 1                                   # 1-based title row
            end = len(col_a)
            for j in range(i + 1, len(col_a)):
                if col_a[j].strip() == TITLE:
                    end = j                                 # row before next title
                    break
            return start, end
    return None


def _rgb(c):
    return {"backgroundColor": c}


def _range(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def format_requests(sid: int, top: int, rows: List[List], colors, whole_pct,
                    green_at: int) -> List[dict]:
    """top = 0-based index of the block's title row."""
    n = len(rows) - 1                                       # without the spacer
    body0, body1 = top + 3, top + n
    reqs = [
        {"mergeCells": {"range": _range(sid, top, top + 1, 0, N_COLS), "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": _range(sid, top, top + 1, 0, N_COLS),
                        "cell": {"userEnteredFormat": {**_rgb(CYAN), "textFormat": {"bold": True, "fontSize": 14}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {"range": _range(sid, top + 1, top + 3, 0, N_COLS),
                        "cell": {"userEnteredFormat": {**_rgb(GREY), "textFormat": {"bold": True},
                                                       "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}},
        {"repeatCell": {"range": _range(sid, body0, body1, 1, N_COLS),
                        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", **_rgb(WHITE)}},
                        "fields": "userEnteredFormat(horizontalAlignment,backgroundColor)"}},
        {"repeatCell": {"range": _range(sid, body0, body1, 0, 1),
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": _range(sid, body1 - 1, body1, 0, N_COLS),
                        "cell": {"userEnteredFormat": {**_rgb(LIGHT), "textFormat": {"bold": True},
                                                       "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}},
        {"updateBorders": {"range": _range(sid, top + 1, body1, 0, N_COLS),
                           **{k: {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}}
                              for k in ("top", "bottom", "left", "right", "innerHorizontal", "innerVertical")}}},
    ]
    for g in range(N_GROUPS):
        c0 = 1 + 8 * g
        reqs.append({"mergeCells": {"range": _range(sid, top + 1, top + 2, c0, c0 + 8),
                                    "mergeType": "MERGE_ALL"}})
        if g == N_GROUPS - 1:
            reqs.append({"repeatCell": {"range": _range(sid, top + 1, top + 2, c0, c0 + 8),
                                        "cell": {"userEnteredFormat": _rgb(CYAN)},
                                        "fields": "userEnteredFormat.backgroundColor"}})
        for off in PCT_OFFSETS:
            reqs.append({"repeatCell": {"range": _range(sid, body0, body1, c0 + off, c0 + off + 1),
                                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                                        "fields": "userEnteredFormat.numberFormat"}})
    for off, c, v in colors:
        if v is None:
            continue
        bg = GREEN if whole_pct(v) >= green_at else RED
        reqs.append({"repeatCell": {"range": _range(sid, top + off, top + off + 1, c, c + 1),
                                    "cell": {"userEnteredFormat": {**_rgb(bg), "textFormat": {"bold": True}}},
                                    "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    return reqs


def write_week(monday: dt.date, days, week, *, pct, whole_pct, sum_rows, green_at: int,
               tab: str = TAB, logfn=print) -> str:
    """Replace this week's block (or put a new one on top). Returns the tab URL."""
    from automations.recruiting_report import fill
    sh = fill.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(tab)
    except Exception:                                       # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=300, cols=N_COLS)
        logfn(f"  sheet: created tab {tab!r}")
    if ws.col_count < N_COLS:
        ws.add_cols(N_COLS - ws.col_count)

    rows, colors = build_block(monday, days, week, pct=pct, whole_pct=whole_pct,
                               sum_rows=sum_rows)
    label = week_label(monday)
    col_a = ws.col_values(1)
    hit = find_block(col_a, label)
    at = 1
    if hit:
        at = hit[0]
        # Unmerge first: a merged title left behind would swallow the new block.
        sh.batch_update({"requests": [{"unmergeCells": {"range": _range(ws.id, hit[0] - 1, hit[1], 0, N_COLS)}}]})
        ws.delete_rows(hit[0], hit[1])
    ws.insert_rows(rows, row=at, value_input_option="RAW")
    sh.batch_update({"requests": format_requests(ws.id, at - 1, rows, colors,
                                                 whole_pct, green_at)})
    logfn(f"  sheet: {tab!r} week {label} written at row {at} ({len(rows) - 5} offices)")
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={ws.id}"
