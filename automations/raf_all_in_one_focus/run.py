"""Fill Raf's 'NEW Focus Report' tab (All in One Local Office - Raf).

Raf's Loom 2026-11-16 ("Update Recruiting and Finance Reports"):
  * match the newer Focus Report layout (the 'Raf Hidalgo' tab of the ATT
    Program - Focus Report) and keep the weeks filled every Monday, backfilled;
  * add the interviewers' weekly numbers ("Recruiting 1st to 2nd Data") from
    ARS REPORT (5) - R to Z -> tab 'Rafael Hidalgo' -> each week's
    'TOTAL for the WEEK', backfilled as far as the ARS goes;
  * add the "Recruiting Data Cost" and "Week 1 Data" sections (typed by hand
    for now -- Maud / Raf -- the math rows are formulas);
  * borders and colors.

What it writes, and what it never touches:
  * Rows are only ever INSERTED (missing labels), never deleted or renamed.
  * Top block (APPS / PULL ... New Starts): copied from the ATT Program tab by
    label + week date, into EMPTY cells only. Raf's typed history stays.
  * 'Recruiting 1st to 2nd Data': ours, a mirror of the ARS -- rewritten every
    run for every closed week the ARS has.
  * Cost / Week 1 rows: formulas only on the math rows; input rows left blank.

Raf's Loom 2026-11-20 ("New Focus Report"): the money rows come from Raf's
"Monthly PNL - Raf's Accounts" -> tab "Hidalgo's finances" (header row
'Fixed Expenses'), column WE X+7 for this tab's WE X (same shift as the
RAF PNL 2026 (NEW) Local Office rows). All positive:
  * Indeed Spending (top block)   = 'Indeed'                     (from WE 8/16/26 on;
    older weeks are Raf's own history and stay as typed)
  * Indeed Spend (cost block)     = Indeed Spending, same week
  * Total Interviewer Spend       = Interviewer #1 .. #5
  * Aptel                         = 'Aptel - Call Center'
  * Aisha                         = 'Aisha - Local Recruiter' + 'Recruiting Bonuses (Aisha)'
Rewritten every run for every week Hidalgo's finances has (Indeed gets
corrected there a week later).

    python -m automations.raf_all_in_one_focus.run --sandbox      # copy tab
    python -m automations.raf_all_in_one_focus.run [--dry-run]    # real tab
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill
from automations.shared.workbooks import ALL_IN_ONE_RAF
from automations.raf_all_in_one_focus import ars_weekly

TARGET_GID = 1428570491
TARGET_TITLE = "NEW Focus Report"
SANDBOX_TITLE = "NEW Focus Report - SANDBOX (Claude)"

ATT_TAB = "Raf Hidalgo"                      # ATT Program - Focus Report
ARS_BOOK = "16UruNs3bHGJ_pBvmD6T9KEqMAtDNNyuKArA_es6f0LE"  # ARS REPORT (5) - R to Z
ARS_TAB = "Rafael Hidalgo"
AI_TAB = "1st rd Recruiter %"                # same workbook, AppStream admin breakdown


def _we(s: str) -> Optional[dt.date]:
    for f in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime((s or "").strip(), f).date()
        except ValueError:
            pass
    return None

# --- top block: rows the newer layout has and this tab is missing ----------
# (anchor label, [labels to insert right below it])
TOP_INSERTS = [
    ("APPS / PULL", ["Duplicate/Already Interviewed", "Total Applies", "Duplicate %"]),
    ("1st Retention", ["AI - Total First Interviews booked",
                       "AI - Total First Interviews Showed",
                       "AI Messaging Retention %"]),
]

# ATT Program label -> this tab's label (count rows only; % rows are formulas)
ATT_TO_TARGET = {
    "Sent To Call List - APPS / PULL": "APPS / PULL",
    "Duplicate/Already Interviewed": "Duplicate/Already Interviewed",
    "Total Applies": "Total Applies",
    "1ST BOOKED": "1ST BOOKED",
    "1ST SHOWED": "1ST SHOWED",
    "AI - Total First Interviews booked": "AI - Total First Interviews booked",
    "AI - Total First Interviews Showed": "AI - Total First Interviews Showed",
    "2ND BOOKED": "2ND BOOKED",
    "2ND SHOWED": "2ND SHOWED",
    "Job Offered": "Job Offered",
    "BOB": "BOB",
    "New Starts Scheduled - TOTAL": "New Starts Scheduled - TOTAL",
    "New Starts Showed - TOTAL": "New Starts Showed - TOTAL",
    "Total Live Accounts": "Total Live Accounts",
    "Total Ads Up": "Total Ads Up",
}

# --- the three sections from the Loom, inserted under NOTES -----------------
H_RECRUIT = "Recruiting 1st to 2nd Data"
H_COST = "Recruiting Data Cost"
H_WEEK1 = "Week 1 Data"

RECRUIT_ROWS = ["Qualified", "Disqualified", "Declined",
                "Qualified Retention", "Disqualified Retention", "Declined Retention",
                "Answered", "Booked", "Not Contacted",
                "Answered Retention", "Booked Retention", "Not Contacted Retention"]
# layout as Raf reshaped it 2026-11-20 (Total 1st Interviewers / Total
# Recruiters rows removed, 'Total Recruiters Spend' = Aptel + Aisha below it)
COST_ROWS = ["Indeed Spend", "Total Interviewer Spend",
             "Total Recruiters Spend", "Aptel", "Aisha",
             "New Start Goodie Bags", "Total RECRUITING SPEND", "CPA",
             "Cost Per 2nd Rd Scheduled", "Cost Per 2nd Rd Showed",
             "Cost Per New Start Scheduled", "Cost Per New Start Showed"]
WEEK1_ROWS = [
    "Monday Showed", "Terminated Monday",
    "Tuesday Showed", "Tuesday Retention From Monday", "Terminated Tuesday",
    "Wednesday Showed", "Wednesday Retention From Monday",
    "Wednesday Retention From Tuesday", "Terminated Wednesday",
    "Thursday Showed", "Thursday Retention From Monday",
    "Thursday Retention From Wednesday", "Terminated Thursday",
    "Friday Showed", "Friday Retention From Monday",
    "Friday Retention From Thursday", "Terminated Friday",
    "Saturday Showed", "Saturday Retention From Monday",
    "Saturday Retention From Friday", "Terminated Saturday",
    "Wk 2 New Starts Showed Up Monday", "Wk 2 New Starts Terminated by EOW",
    "Wk 2 New Starts Around EOW", "Wk 2 New Start Retention",
    "Wk 3 New Starts Showed Up Monday", "Wk 3 New Starts Terminated by EOW",
    "Wk 3 New Starts Around EOW", "Wk 3 New Start Retention",
    "Wk 4 New Starts Showed Up Monday", "Wk 4 New Starts Terminated by EOW",
    "Wk 4 New Starts Around EOW", "Wk 4 New Start Retention",
]
NEW_BLOCK = ([""] + [H_RECRUIT] + RECRUIT_ROWS + [""] + [H_COST] + COST_ROWS
             + [""] + [H_WEEK1] + WEEK1_ROWS + [""])

ARS_KEY = {"Qualified": "qualified", "Disqualified": "disqualified",
           "Declined": "declined", "Answered": "answered", "Booked": "booked",
           "Not Contacted": "not_contacted"}

PCT_ROWS = {"Duplicate %", "AI Messaging Retention %", "Qualified Retention",
            "Disqualified Retention", "Declined Retention", "Answered Retention",
            "Booked Retention", "Not Contacted Retention",
            "Tuesday Retention From Monday", "Wednesday Retention From Monday",
            "Wednesday Retention From Tuesday", "Thursday Retention From Monday",
            "Thursday Retention From Wednesday", "Friday Retention From Monday",
            "Friday Retention From Thursday", "Saturday Retention From Monday",
            "Saturday Retention From Friday", "Wk 2 New Start Retention",
            "Wk 3 New Start Retention", "Wk 4 New Start Retention"}
MONEY_ROWS = set(COST_ROWS)                  # every cost row is dollars

# --- money rows from Hidalgo's finances (Raf Loom 2026-11-20) ---------------
RAF_PNL_BOOK = "1M2Vy2qo3N1AND1tVuKugtT_FizYw_6lBD3t2tcRLFYg"   # Monthly PNL - Raf's Accounts
HIDALGO_TAB = "Hidalgo's finances"
HIDALGO_HDR = "fixed expenses"               # col A of the weekly header row
INDEED_FROM = dt.date(2026, 8, 16)           # Indeed Spending written from this WE on
# this tab's label -> Hidalgo's finances labels to add up (absolute values)
HIDALGO_MAP = {
    "Indeed Spending": ["Indeed"],
    "Total Interviewer Spend": [f"Interviewer #{i}" for i in range(1, 6)],
    "Aptel": ["Aptel - Call Center"],
    "Aisha": ["Aisha - Local Recruiter", "Recruiting Bonuses (Aisha)"],
}


def _money(s) -> Optional[float]:
    t = str(s or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if t in ("", "-"):
        return 0.0 if t == "-" else None
    neg = t.startswith("(") and t.endswith(")")
    try:
        v = float(t.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def hidalgo_weeks(gc, log=print) -> Dict[dt.date, Dict[str, float]]:
    """{this tab's WE: {label: positive amount}} from Hidalgo's finances.
    Its 'WE m.d' column X+7 belongs to this tab's WE X."""
    vals = fill.open_by_key(RAF_PNL_BOOK, client=gc).worksheet(HIDALGO_TAB).get_all_values()
    hi = next(i for i, row in enumerate(vals) if row and norm(row[0]) == HIDALGO_HDR
              and any(re.match(r"\s*WE\s+\d", x or "") for x in row[1:]))
    rows = {norm(row[0]): row for row in vals[hi + 1:] if row and row[0].strip()}
    out: Dict[dt.date, Dict[str, float]] = {}
    year, prev_m = None, None
    for j, h in enumerate(vals[hi]):
        m = re.match(r"\s*WE\s+(\d+)\.(\d+)", h or "")
        if not m or j == 0:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        # newest first, no year in the header: walk back from this year
        if year is None:
            t = dt.date.today()
            year = t.year - 1 if mo - t.month > 6 else t.year + 1 if t.month - mo > 6 else t.year
        elif mo > prev_m:
            year -= 1
        prev_m = mo
        we = dt.date(year, mo, d) - dt.timedelta(days=7)
        got = {}
        for dst, srcs in HIDALGO_MAP.items():
            parts = [_money(rows[norm(s)][j]) if norm(s) in rows and j < len(rows[norm(s)]) else None
                     for s in srcs]
            if all(p is None for p in parts):
                continue
            got[dst] = round(sum(abs(p) for p in parts if p is not None), 2)
        if got:
            out[we] = got
    if out:
        log(f"  Hidalgo's finances: {len(out)} week(s) "
            f"({min(out)} .. {max(out)}, as this tab's WE)")
    return out


def norm(s: str) -> str:
    return " ".join(str(s or "").split()).lower()


def a1col(n: int) -> str:                    # 1-indexed
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def last_sunday(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


# ----------------------------------------------------------------- lookups
def label_rows(col_b: List[str], stop_label: str = "office performance tracker") -> Dict[str, int]:
    """{normalised label: 1-indexed row} for col B, first occurrence, above the
    first OPT block (whose labels repeat some of the top block's)."""
    out: Dict[str, int] = {}
    for i, v in enumerate(col_b, start=1):
        k = norm(v)
        if not k:
            continue
        if i > 1 and stop_label in k:
            break
        out.setdefault(k, i)
    return out


def col_a_stop(col_a: List[str]) -> Optional[int]:
    for i, v in enumerate(col_a, start=1):
        if norm(v) == "office goals":
            return i
    return None


# ----------------------------------------------------------------- layout
def ensure_layout(ws, dry_run: bool, log=print) -> bool:
    """Insert the missing rows. Never deletes, never renames. True if it inserted."""
    sh = ws.spreadsheet
    col_b = ws.col_values(2)
    rows = label_rows(col_b)
    reqs, inserts = [], []                    # inserts: (after_row, labels)
    for anchor, labels in TOP_INSERTS:
        missing = [l for l in labels if norm(l) not in rows]
        if not missing:
            continue
        if norm(anchor) not in rows:
            raise LookupError(f"anchor row {anchor!r} not found in col B")
        inserts.append((rows[norm(anchor)], missing))
    if norm(H_RECRUIT) not in rows:
        if "notes" not in rows:
            raise LookupError("NOTES row not found in col B")
        inserts.append((rows["notes"], NEW_BLOCK))

    # bottom-up so earlier row numbers stay valid
    for after, labels in sorted(inserts, key=lambda t: -t[0]):
        log(f"  insert {len(labels)} row(s) below row {after}: "
            f"{', '.join(l for l in labels if l)[:90]}")
        reqs.append({"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": after, "endIndex": after + len(labels)},
            "inheritFromBefore": False}})
    if not reqs:
        log("  layout already complete")
        return False
    if dry_run:
        return True
    sh.batch_update({"requests": reqs})
    # write labels (top-down; recompute positions after the inserts)
    data, shift = [], 0
    for after, labels in sorted(inserts, key=lambda t: t[0]):
        start = after + 1 + shift
        data.append({"range": f"B{start}:B{start + len(labels) - 1}",
                     "values": [[l] for l in labels]})
        shift += len(labels)
    ws.batch_update(data, value_input_option="USER_ENTERED")
    return True


# ----------------------------------------------------------------- formulas
def formulas_for(col: str, prev2: Optional[str], r: Dict[str, int],
                 fill_blank_pct: bool = True) -> Dict[int, str]:
    """{row: formula} for one week column. `r` maps normalised label -> row."""
    def c(label):                             # cell ref in this column
        return f"{col}{r[norm(label)]}"
    f: Dict[int, str] = {}

    def put(label, formula):
        # `formula` is a lambda: a row it needs that is not on the tab yet
        # (dry run before the inserts) just skips that formula
        if norm(label) in r:
            try:
                body = formula()
            except KeyError:
                return
            wrapped = body.upper().startswith("=IFERROR(")
            f[r[norm(label)]] = body if wrapped else f'=IFERROR({body[1:]},"")'

    if fill_blank_pct:
        put("Retention to Call list", lambda: f'=IFERROR({c("1ST BOOKED")}/{c("APPS / PULL")},0)')
        put("Retention 1st showed Booked for 2nd", lambda: f'=IFERROR({c("2ND BOOKED")}/{c("1ST SHOWED")},0)')
    put("Duplicate %", lambda: f'=IF({c("Total Applies")}="","",IFERROR({c("Duplicate/Already Interviewed")}/{c("Total Applies")},0))')
    put("AI Messaging Retention %", lambda: f'=IF({c("AI - Total First Interviews booked")}="","",IFERROR({c("AI - Total First Interviews Showed")}/{c("AI - Total First Interviews booked")},0))')

    def shown():
        return f'({c("Qualified")}+{c("Disqualified")}+{c("Declined")})'
    for lbl, num in (("Qualified Retention", "Qualified"),
                     ("Disqualified Retention", "Disqualified"),
                     ("Declined Retention", "Declined")):
        put(lbl, lambda: f'=IF({c("Qualified")}="","",IFERROR({c(num)}/{shown()},0))')
    for lbl, num in (("Answered Retention", "Answered"),
                     ("Booked Retention", "Booked"),
                     ("Not Contacted Retention", "Not Contacted")):
        put(lbl, lambda: f'=IF({c(num)}="","",IFERROR({c(num)}/{c("Qualified")},0))')

    # Indeed Spend = Indeed Spending of the SAME week (Raf 2026-11-20; the
    # Hidalgo's finances WE+7 shift already lines the bill up with the week)
    put("Indeed Spend", lambda: f'=IF({c("Indeed Spending")}="","",{c("Indeed Spending")})')
    put("Total Recruiters Spend", lambda: f'=IF(COUNT({c("Aptel")},{c("Aisha")})=0,"",SUM({c("Aptel")},{c("Aisha")}))')
    put("New Start Goodie Bags", lambda: f'=IF(OR($A{r[norm("New Start Goodie Bags")]}="",{c("New Starts Showed - TOTAL")}=""),"",$A{r[norm("New Start Goodie Bags")]}*{c("New Starts Showed - TOTAL")})')
    spend = [f"{col}{r[norm(l)]}" for l in ("Indeed Spend", "Total Interviewer Spend",
             "Total Recruiters Spend", "New Start Goodie Bags") if norm(l) in r]
    put("Total RECRUITING SPEND", lambda: f'=IF(COUNT({",".join(spend)})=0,"",SUM({",".join(spend)}))')
    put("CPA", lambda: f'=IF(OR({c("Indeed Spend")}="",{c("Total Applies")}=""),"",IFERROR({c("Indeed Spend")}/{c("Total Applies")},""))')
    for lbl, den in (("Cost Per 2nd Rd Scheduled", "2ND BOOKED"),
                     ("Cost Per 2nd Rd Showed", "2ND SHOWED"),
                     ("Cost Per New Start Scheduled", "New Starts Scheduled - TOTAL"),
                     ("Cost Per New Start Showed", "New Starts Showed - TOTAL")):
        put(lbl, lambda: f'=IF(OR({c("Total RECRUITING SPEND")}="",{c(den)}=""),"",IFERROR({c("Total RECRUITING SPEND")}/{c(den)},""))')
    return f


# ----------------------------------------------------------------- styling
def _rgb(h: str) -> dict:
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


SECTION_BG = _rgb("#0b5394")      # dark blue section headers, white text
PURPLE = _rgb("#932e87")          # Qualified / Disqualified / Declined (Eve)
ORANGE = _rgb("#b45f06")          # Answered / Booked / Not Contacted (Eve)
GREEN = _rgb("#38761d")           # cost inputs
TEAL = _rgb("#134f5c")            # cost results
GREY = _rgb("#f3f3f3")            # retention label rows
WK1 = _rgb("#e69138")             # week 1 data counts
WHITE = {"red": 1, "green": 1, "blue": 1}
BLACK = {"red": 0, "green": 0, "blue": 0}
_SOLID = {"style": "SOLID", "color": BLACK}


def style_requests(sheet_id: int, r: Dict[str, int], last_col: int) -> List[dict]:
    reqs: List[dict] = []

    def fmt(row, c0, c1, f, fields):
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": f}, "fields": fields}})

    def label(lbl, bg, fg=WHITE):
        if norm(lbl) in r:
            fmt(r[norm(lbl)], 1, 2, {"backgroundColor": bg, "horizontalAlignment": "CENTER",
                                     "textFormat": {"bold": True, "foregroundColor": fg}},
                "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)")

    for h in (H_RECRUIT, H_COST, H_WEEK1):
        if norm(h) in r:
            fmt(r[norm(h)], 0, last_col, {"backgroundColor": SECTION_BG,
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "foregroundColor": WHITE}},
                "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)")
    for l in ("Qualified", "Disqualified", "Declined"):
        label(l, PURPLE)
    for l in ("Answered", "Booked", "Not Contacted"):
        label(l, ORANGE)
    for l in ("Indeed Spend", "Total Interviewer Spend",
              "Aptel", "Aisha", "New Start Goodie Bags"):
        label(l, GREEN)
    for l in ("Total Recruiters Spend", "Total RECRUITING SPEND", "CPA",
              "Cost Per 2nd Rd Scheduled", "Cost Per 2nd Rd Showed",
              "Cost Per New Start Scheduled", "Cost Per New Start Showed"):
        label(l, TEAL)
    for l in WEEK1_ROWS:
        if l in PCT_ROWS:
            label(l, GREY, BLACK)
        else:
            label(l, WK1)
    for l in ("Qualified Retention", "Disqualified Retention", "Declined Retention",
              "Answered Retention", "Booked Retention", "Not Contacted Retention",
              "Duplicate %", "AI Messaging Retention %"):
        label(l, GREY, BLACK)
    for l in ("Duplicate/Already Interviewed", "Total Applies"):
        label(l, _rgb("#ffabbb"), BLACK)        # same pink as APPS / PULL
    for l in ("AI - Total First Interviews booked", "AI - Total First Interviews Showed"):
        label(l, _rgb("#90ee8f"), BLACK)        # same green as 1ST BOOKED

    for l in ("Duplicate/Already Interviewed", "Total Applies",
              "AI - Total First Interviews booked", "AI - Total First Interviews Showed"):
        if norm(l) in r:
            fmt(r[norm(l)], 2, last_col, {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
                                          "horizontalAlignment": "CENTER"},
                "userEnteredFormat(numberFormat,horizontalAlignment)")

    # number formats + centered values on every row we own
    for l, row in r.items():
        pretty = next((x for x in PCT_ROWS | MONEY_ROWS if norm(x) == l), None)
        if pretty in PCT_ROWS:
            nf = {"type": "PERCENT", "pattern": "0%"}
        elif pretty in MONEY_ROWS:
            nf = {"type": "CURRENCY", "pattern": "$#,##0.00"}
        else:
            continue
        fmt(row, 2, last_col, {"numberFormat": nf, "horizontalAlignment": "CENTER"},
            "userEnteredFormat(numberFormat,horizontalAlignment)")

    # borders: each new section, label col through the last week column
    def box(first, last):
        reqs.append({"updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": first - 1, "endRowIndex": last,
                      "startColumnIndex": 1, "endColumnIndex": last_col},
            "top": _SOLID, "bottom": _SOLID, "left": _SOLID, "right": _SOLID,
            "innerHorizontal": _SOLID, "innerVertical": _SOLID}})
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": first, "endRowIndex": last,
                      "startColumnIndex": 2, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}})
    for head, body in ((H_RECRUIT, RECRUIT_ROWS), (H_COST, COST_ROWS), (H_WEEK1, WEEK1_ROWS)):
        if norm(head) in r and norm(body[-1]) in r:
            box(r[norm(head)], r[norm(body[-1])])
    # The top block and the OPT blocks are Raf's: their borders (thick lines
    # between groups) are NOT overwritten here -- fill_missing_borders() only
    # adds the sides that are missing.
    return reqs


INSERTED_LABELS = {norm(l) for _, ls in TOP_INSERTS for l in ls} |     {norm(l) for l in NEW_BLOCK if l}


def _sides(c: dict) -> dict:
    return (c.get("effectiveFormat", {}) or {}).get("borders", {}) or {}


def blocks_to_border(labels: List[str], last_label_row: Optional[int] = None) -> List[Tuple[int, int]]:
    """(first row, last row) of the top block (row 1 .. NOTES) and of every
    '... Office Performance Tracker' block (header .. last row before a blank
    label). 1-indexed."""
    out = []
    notes = next((i for i, l in enumerate(labels, 1) if norm(l) == "notes"), None)
    if notes:
        out.append((1, notes))
    for i, l in enumerate(labels, 1):
        if "office performance tracker" in norm(l):
            j = i
            while j < len(labels) and norm(labels[j]):    # labels[j] is row j+1
                j += 1
            out.append((i, j))
    return out


def fill_missing_borders(ws, last_col: int, log=print) -> int:
    """Add a thin border on every side that has none (looking at the
    neighbour too: a cell's missing bottom is fine if the cell below has a
    top). Existing borders, thick or thin, are kept as they are."""
    labels = ws.col_values(2)
    blocks = blocks_to_border(labels)
    if not blocks:
        return 0
    solid = {"style": "SOLID", "color": BLACK}
    reqs, fixed = [], 0
    for first, last in blocks:
        rng = f"'{ws.title}'!A{max(first - 1, 1)}:{a1col(last_col + 1)}{last + 1}"
        meta = ws.spreadsheet.fetch_sheet_metadata({
            "ranges": [rng], "includeGridData": True,
            "fields": "sheets(data(startRow,rowData(values(effectiveFormat(borders)))))"})
        data = meta["sheets"][0]["data"][0]
        row0 = data.get("startRow", 0) + 1                 # 1-indexed first row read
        grid = [rd.get("values", []) for rd in data.get("rowData", [])]

        def cell(r, c):                                    # 1-indexed
            i, j = r - row0, c - 1
            return grid[i][j] if 0 <= i < len(grid) and 0 <= j < len(grid[i]) else {}

        rows_out = []
        for r in range(first, last + 1):
            vals, any_fix = [], False
            for c in range(2, last_col + 1):              # B .. last week column
                b = dict(_sides(cell(r, c)))
                need = {
                    "top": not b.get("top") and not _sides(cell(r - 1, c)).get("bottom"),
                    "bottom": not b.get("bottom") and not _sides(cell(r + 1, c)).get("top"),
                    "left": not b.get("left") and not _sides(cell(r, c - 1)).get("right"),
                    "right": not b.get("right") and not _sides(cell(r, c + 1)).get("left"),
                }
                for side, missing in need.items():
                    if missing:
                        b[side] = solid
                        any_fix = True
                        fixed += 1
                vals.append({"userEnteredFormat": {"borders": b}})
            rows_out.append((r, vals, any_fix))
        for r, vals, any_fix in rows_out:
            if any_fix:
                reqs.append({"updateCells": {
                    "range": {"sheetId": ws.id, "startRowIndex": r - 1, "endRowIndex": r,
                              "startColumnIndex": 1, "endColumnIndex": last_col},
                    "rows": [{"values": vals}], "fields": "userEnteredFormat.borders"}})
    if reqs:
        ws.spreadsheet.batch_update({"requests": reqs})
    log(f"  borders: {fixed} missing side(s) added in {len(blocks)} block(s)")
    return fixed


def shift_rows(formula: str, delta: int) -> str:
    """'=C3:AK3>=$A3' +3 -> '=C6:AK6>=$A6' (relative row numbers only;
    '$3' rows and text in quotes are left alone)."""
    import re
    parts = formula.split('"')
    for i in range(0, len(parts), 2):                     # outside quotes
        parts[i] = re.sub(r"(\$?[A-Z]{1,3})(\$?)(\d+)(?![\d(])",
                          lambda m: m.group(0) if m.group(2) else
                          f"{m.group(1)}{int(m.group(3)) + delta}", parts[i])
    return '"'.join(parts)


def fix_conditional_formats(ws, log=print) -> int:
    """Take the rows we inserted back OUT of the tab's conditional-format
    ranges. Inserting rows inside a range stretches it, and an empty cell
    then passes '>= goal' and shows green across the whole row."""
    labels = ws.col_values(2)
    ours = {i - 1 for i, l in enumerate(labels, 1) if norm(l) in INSERTED_LABELS}  # 0-idx
    # blank spacer rows inside our block count as ours too
    if norm(H_RECRUIT) in {norm(l) for l in labels}:
        start = next(i for i, l in enumerate(labels, 1) if norm(l) == norm(H_RECRUIT))
        ours |= set(range(start - 2, start - 1 + len(NEW_BLOCK) - 1))
    meta = ws.spreadsheet.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId),conditionalFormats)"})
    rules = next(s.get("conditionalFormats", []) for s in meta["sheets"]
                 if s["properties"]["sheetId"] == ws.id)
    reqs = []
    for idx, rule in enumerate(rules):
        new_ranges, changed = [], False
        for rg in rule["ranges"]:
            a, b = rg.get("startRowIndex", 0), rg.get("endRowIndex", ws.row_count)
            run_start = None
            for row in range(a, b + 1):
                inside = row < b and row not in ours
                if inside and run_start is None:
                    run_start = row
                elif not inside and run_start is not None:
                    new_ranges.append({**rg, "startRowIndex": run_start, "endRowIndex": row})
                    run_start = None
            if any(a <= x < b for x in ours):
                changed = True
        if changed and new_ranges:
            # A custom formula is written relative to the FIRST range's
            # top-left cell. If that cell moved, move the formula's relative
            # rows with it, or every cell compares against the wrong row.
            old_top = min(rg.get("startRowIndex", 0) for rg in rule["ranges"][:1])
            new_top = new_ranges[0].get("startRowIndex", 0)
            rule = {**rule, "ranges": new_ranges}
            if new_top != old_top and "booleanRule" in rule:
                cond = rule["booleanRule"].get("condition", {})
                for v in cond.get("values", []):
                    if str(v.get("userEnteredValue", "")).startswith("="):
                        v["userEnteredValue"] = shift_rows(v["userEnteredValue"], new_top - old_top)
            reqs.append({"updateConditionalFormatRule": {
                "index": idx, "sheetId": ws.id, "rule": rule}})
    if reqs:
        ws.spreadsheet.batch_update({"requests": reqs})
    log(f"  conditional formats: {len(reqs)} rule(s) narrowed off the inserted rows")
    return len(reqs)


# ----------------------------------------------------------------- main
def open_target(sh, sandbox: bool, dry_run: bool, log=print):
    if not sandbox:
        return sh.get_worksheet_by_id(TARGET_GID)
    for w in sh.worksheets():
        if w.title == SANDBOX_TITLE:
            return w
    if dry_run:
        log(f"  (dry run) would duplicate {TARGET_TITLE!r} -> {SANDBOX_TITLE!r}")
        return sh.get_worksheet_by_id(TARGET_GID)
    src = sh.get_worksheet_by_id(TARGET_GID)
    log(f"  duplicating {src.title!r} -> {SANDBOX_TITLE!r}")
    return sh.duplicate_sheet(src.id, insert_sheet_index=src.index + 1,
                              new_sheet_name=SANDBOX_TITLE)


def wrap_div_errors(ws, log=print) -> int:
    """Maud 2026-11-27: on this tab a division never shows #DIV/0! -- every formula
    that divides (or currently errors) is wrapped as =IFERROR(...,0). Idempotent."""
    vals = ws.get_all_values()
    forms = ws.get_all_values(value_render_option="FORMULA")
    data = []
    for i, row in enumerate(forms):
        for j, x in enumerate(row):
            if not (isinstance(x, str) and x.startswith("=")) or x.upper().startswith("=IFERROR("):
                continue
            v = vals[i][j] if i < len(vals) and j < len(vals[i]) else ""
            if v == "#DIV/0!" or "/" in re.sub(r"'[^']*'|\"[^\"]*\"", "", x):
                data.append({"range": f"{a1col(j + 1)}{i + 1}", "values": [[f"=IFERROR({x[1:]},0)"]]})
    for k in range(0, len(data), 2000):
        ws.batch_update(data[k:k + 2000], value_input_option="USER_ENTERED")
    log(f"  IFERROR-wrapped {len(data)} division formula(s)")
    return len(data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sandbox", action="store_true",
                    help=f"work on the copy tab {SANDBOX_TITLE!r} (created if missing)")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--style", action="store_true",
                    help="re-apply colors/borders/number formats (default: only when rows were just inserted)")
    args = ap.parse_args(argv)
    log = print
    today = dt.date.today()
    closed = last_sunday(today)

    gc = fill._client()
    sh = fill.open_by_key(ALL_IN_ONE_RAF, client=gc)
    ws = open_target(sh, args.sandbox, args.dry_run, log)
    log(f"Target: All in One Local Office - Raf -> {ws.title!r}")

    inserted = ensure_layout(ws, args.dry_run, log)

    values = ws.get_all_values(value_render_option="FORMATTED_VALUE")
    weeks = fill.find_sunday_columns(values)            # {date: 1-idx col}
    r = label_rows([row[1] if len(row) > 1 else "" for row in values])
    # our sections sit above OFFICE GOALS, so label_rows already has them
    last_col = max(weeks.values()) if weeks else len(values[0])

    def cur(row, col):
        try:
            return values[row - 1][col - 1].strip()
        except IndexError:
            return ""

    updates: List[Tuple[int, int, object]] = []        # (row, col, value)

    # 1) top block from the ATT Program tab, empty cells only
    att = fill.worksheet_ci(fill.open_by_key(fill.SPREADSHEET_ID, client=gc), ATT_TAB)
    av = att.get("A1:ZZ40", value_render_option="UNFORMATTED_VALUE")
    a_weeks = fill.find_sunday_columns(
        [[(dt.date(1899, 12, 30) + dt.timedelta(days=int(x))).strftime("%m/%d/%Y")
          if isinstance(x, (int, float)) and x > 40000 else str(x) for x in av[0]]])
    a_rows = label_rows([row[1] if len(row) > 1 else "" for row in av])
    top_filled = 0
    for src_lbl, dst_lbl in ATT_TO_TARGET.items():
        sr, dr = a_rows.get(norm(src_lbl)), r.get(norm(dst_lbl))
        if not sr or not dr:
            continue
        for wk, dc in weeks.items():
            # a 0 counts as empty (Maud 2026-11-27: WE 11/22 Total Applies stuck at 0
            # after an early copy) -- replaced once the ATT tab has a real number
            if wk > closed or wk not in a_weeks or cur(dr, dc) not in ("", "0"):
                continue
            row = av[sr - 1]
            v = row[a_weeks[wk] - 1] if a_weeks[wk] - 1 < len(row) else ""
            if v == "" or v is None or (v == 0 and cur(dr, dc) == "0"):
                continue
            updates.append((dr, dc, v))
            top_filled += 1
    log(f"  top block: {top_filled} empty cell(s) filled from ATT Program '{ATT_TAB}'")

    # 1b) AI rows from the '1st rd Recruiter %' tab (same workbook): AppStream's
    # Retention Report with the admin breakdown on, 'AI Messaging' under Total
    # First Interviews (Sch) / First Interviews Showed Up (SU). Same week-ending
    # Sunday columns as this tab. Empty cells only.
    n_ai = 0
    try:
        rt = sh.worksheet(AI_TAB).get_all_values()
        hdr = next(i for i, row in enumerate(rt) if sum(1 for x in row if _we(x)) >= 2)
        ai = next(row for row in rt if row and norm(row[0]) == "ai messaging")
        for j, x in enumerate(rt[hdr]):
            wk = _we(x)
            if not wk or wk > closed or wk not in weeks:
                continue
            for lbl, off in (("AI - Total First Interviews booked", 0),
                             ("AI - Total First Interviews Showed", 1)):
                dr = r.get(norm(lbl))
                v = ai[j + off].strip() if j + off < len(ai) else ""
                if dr and v and not cur(dr, weeks[wk]):
                    updates.append((dr, weeks[wk], int(v.replace(",", ""))))
                    n_ai += 1
    except (StopIteration, ValueError) as e:
        log(f"  AI rows: '{AI_TAB}' not readable ({e!r}), skipped")
    log(f"  AI rows: {n_ai} empty cell(s) filled from '{AI_TAB}' (AI Messaging)")

    # 1c) Raf's 'Total interviewer slots' box: its formula lost its inputs
    # (=SUM(#REF!*#REF!)). Point it back at Interviewers x Slots per interviewer
    # on the same row; blank until Raf types them.
    fv = ws.get_all_values(value_render_option="FORMULA")
    for i, row in enumerate(fv):
        for j, x in enumerate(row):
            if norm(x) == "total interviewer slots" and j >= 2:
                f = fv[i + 1][j] if i + 1 < len(fv) and j < len(fv[i + 1]) else ""
                if "#REF!" in f:
                    a, b = a1col(j - 1), a1col(j)
                    updates.append((i + 2, j + 1,
                                    f'=IF(OR({a}{i + 2}="",{b}{i + 2}=""),"",{a}{i + 2}*{b}{i + 2})'))
                    log(f"  fixed #REF in {a1col(j + 1)}{i + 2} (Total interviewer slots)")
                # the 'showed' line under it halves that cell; keep it blank too
                g = fv[i + 2][j] if i + 2 < len(fv) and j < len(fv[i + 2]) else ""
                m = re.fullmatch(r"=SUM\(([A-Z]+\d+)/2\)", g.replace(" ", ""))
                if m:
                    updates.append((i + 3, j + 1, f'=IF({m.group(1)}="","",{m.group(1)}/2)'))

    # 2) interviewer numbers from the ARS
    ars_ws = fill.open_by_key(ARS_BOOK, client=gc).worksheet(ARS_TAB)
    # The tab is ~8,500 rows of applicant log; the weekly boxes sit in the
    # first few hundred. Find where the box label column ends, read only that.
    row1 = ars_ws.row_values(1)
    q_idx = next(j for j, v in enumerate(row1, 1)
                 if ars_weekly._norm(v) == ars_weekly.QUALIFIED_BANNER)
    box_col = ars_ws.col_values(q_idx)
    ars_rows = ars_ws.get(f"A1:{a1col(len(row1))}{len(box_col) + 2}")
    totals = ars_weekly.weekly_totals(ars_rows, today)
    n_ars = 0
    for wk, t in sorted(totals.items()):
        if wk > closed or wk not in weeks:
            continue
        for lbl, key in ARS_KEY.items():
            if key in t and norm(lbl) in r:
                v = t[key]
                updates.append((r[norm(lbl)], weeks[wk], int(v) if v == int(v) else v))
                n_ars += 1
    have = [w for w in sorted(totals) if w <= closed]
    log(f"  interviewers: {len(have)} week(s) from ARS "
        f"({have[0] if have else '-'} .. {have[-1] if have else '-'}), {n_ars} cells")

    # 2b) money rows from Hidalgo's finances (rewritten every run)
    n_h = 0
    for wk, got in sorted(hidalgo_weeks(gc, log).items()):
        if wk > closed or wk not in weeks:
            continue
        for lbl, v in got.items():
            if lbl == "Indeed Spending" and wk < INDEED_FROM:
                continue
            row = r.get(norm(lbl))
            if row:
                updates.append((row, weeks[wk], v))
                n_h += 1
    log(f"  money rows: {n_h} cell(s) from {HIDALGO_TAB!r} (WE+7 column)")

    # 3) formulas on every week column
    cols = sorted(weeks.items())
    n_f = 0
    for i, (wk, c) in enumerate(cols):
        prev2 = a1col(cols[i - 2][1]) if i >= 2 else None
        for row, f in formulas_for(a1col(c), prev2, r).items():
            # Raf's own % rows: only where the cell is empty
            if row in (r.get("retention to call list"),
                       r.get("retention 1st showed booked for 2nd")) and cur(row, c):
                continue
            updates.append((row, c, f))
            n_f += 1
    log(f"  formulas: {n_f} cells across {len(cols)} week columns")

    if args.dry_run:
        for row, col, v in [u for u in updates if not str(u[2]).startswith("=")][-15:]:
            log(f"    {a1col(col)}{row} ({values[0][col-1]} / {cur(row, 2)}) <- {v}")
        log("DRY RUN: nothing written")
        return 0

    data = [{"range": f"{a1col(c)}{row}", "values": [[v]]} for row, c, v in updates]
    for i in range(0, len(data), 2000):
        ws.batch_update(data[i:i + 2000], value_input_option="USER_ENTERED")
    # Raf formats the tab himself (Loom 2026-11-20): style only the rows we
    # just inserted, never repaint on a normal weekly run.
    if inserted or args.style:
        sh.batch_update({"requests": style_requests(ws.id, r, last_col)})
        fix_conditional_formats(ws, log)
        fill_missing_borders(ws, last_col, log)
    wrap_div_errors(ws, log)
    log(f"Done: {len(updates)} cells written to {ws.title!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
