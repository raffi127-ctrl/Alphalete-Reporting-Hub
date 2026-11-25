"""Finish a 'CS m.d' commission sheet after the snapshot (Carlos 2026-11-24).

Two things the Apps Script render leaves wrong on every CS tab:

1. FIRST & SECOND WEEK PAYCHECKS reads the old 'Activations' tab (B2B DTR), so
   NDS reps showed 0 orders / 0 apps. Counted here off the NDS Order Log (the
   SaraPlus feed): Order Count = distinct DSI #s, Total Apps = Port lines (what
   the sales board counts as an app; new numbers and upgrades are not apps).
   Cancelled lines are out. Orders dated after the week's Sunday are out, so a
   re-snap shows the same numbers. Plus a 4th column, Training Bonuses: what
   earlier weeks already paid, read off the Adjustments labels.
2. Borders left over from longer lists in columns A:E under the TOTAL row.

3. A Rate column left of NPA's (Carlos 11/24: "added this rate tab so you can see
what people are getting paid ... move it to the left of the NPA's column, and ...
spacing between F and G so the columns aren't touching the actual commission
sheet"): E = Rate, F = NPA's, G = empty, the itemized block starts at H.

4. PAY LEVELS check (Carlos 11/24): "whatever they do on a Monday through Sunday,
that following Friday's paycheck percentage payout is determined by that Monday
through Sunday." Leaders (Level 1+): 10 apps = 45%, 14 apps = 50%. The check only
REPORTS who is due and not paid it; pay is changed by an Adjustments Bonus row
labelled '45% pay - 10 apps last week', which the Rate column then reads.

5. Percentage Payout (Carlos 11/24: "instead of the 45% looking like a bonus on
the commission sheets, let's just add a column that says 'Percentage Payout' in
between columns N and O, and just add in the rate on there"): between Total $ to
ICD and Commission, each line's own %. A pay-level row ('45% pay - ...', 'Paid
at 30%') is not shown as a bonus line; its lines are shown at that % instead.
The rep's total is the same either way and the engine tab is untouched.

Final columns: A Rep .. D Profit/Loss | E Rate | F NPA's | G empty | H REP Name
.. O Total $ to ICD | P Percentage Payout | Q Commission | S:T Brought In box.

Runs on the CS copy only, never on the Commission engine tab.
"""
from __future__ import annotations

import datetime as dt
import re

NO_REV = "ACTIVE REPS - NO REVENUE"
REV_NOT = "REVENUE - NOT ACTIVE"
FIRST_SECOND = "FIRST & SECOND WEEK PAYCHECKS"
BONUS_HDR = "Training Bonuses"


def _tok(s) -> list:
    return "".join(c if c.isalnum() else " " for c in str(s or "").lower()).split()


def canon(name, aliases: dict) -> str:
    return aliases.get(str(name or "").strip().lower(), str(name or "").strip())


def name_match(a, b, aliases: dict = None) -> bool:
    """Payroll.gs _nmMatch: one name's words inside the other's, or same last
    name with one first name starting the other."""
    al = aliases or {}
    x, y = _tok(canon(a, al)), _tok(canon(b, al))
    if not x or not y:
        return False
    if set(x) <= set(y) or set(y) <= set(x):
        return True
    return x[-1] == y[-1] and (x[0].startswith(y[0]) or y[0].startswith(x[0]))


def week_date(label, ref: dt.date):
    """'11.15' -> that Sunday on or before `ref`'s year end. The sheet stores
    8.30 as 8.3, so a day that is not a Sunday is read as x10."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\s*$", str(label))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    for year in (ref.year, ref.year - 1):
        for day in ([d, d * 10] if len(m.group(2)) == 1 else [d]):
            try:
                got = dt.date(year, mo, day)
            except ValueError:
                continue
            if got.weekday() == 6 and got <= ref:
                return got
    return None


def _mdy(s):
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(s))
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def order_counts(order_vals, names, through: dt.date, aliases: dict = None,
                 order_col: str = "dsi #") -> dict:
    """{name: (orders, apps)} off an order log tab's values (NDS: 'DSI #';
    the Verizon Order Log: 'Order #')."""
    out = {n: (0, 0) for n in names}
    if not order_vals:
        return out
    hdr = [str(h).strip().lower() for h in order_vals[0]]
    need = {k: hdr.index(k) for k in ("rep", order_col, "line status", "type", "order date")}
    by_rep = {}
    for r in order_vals[1:]:
        r = list(r) + [""] * (len(hdr) - len(r))
        if not str(r[need["rep"]]).strip():
            continue
        if "cancel" in str(r[need["line status"]]).lower():
            continue
        if str(r[need["type"]]).strip().lower() != "port":
            continue
        d = _mdy(r[need["order date"]])
        if d and d > through:
            continue
        o = by_rep.setdefault(str(r[need["rep"]]).strip(), {})
        key = str(r[need[order_col]]).strip() or f"row{len(o)}"
        o[key] = o.get(key, 0) + 1
    for n in names:
        orders = apps = 0
        for rep, o in by_rep.items():
            if name_match(n, rep, aliases):
                orders += len(o)
                apps += sum(o.values())
        out[n] = (orders, apps)
    return out


def bonus_numbers(label) -> dict:
    """{1: 'full'|'partial', 2: ...} named by one Adjustments label; {0: 'full'}
    = a training bonus with no number; {} = not a training bonus."""
    s = re.sub(r"\([^)]*\)", " ", str(label or "")).lower()
    if "train" not in s:
        return {}
    s = re.sub(r"\$\s*[\d,.]+", " ", s)
    part = "partial" if "partial" in s else "full"
    got = {}
    if re.search(r"\b(one|first|1st|#?1)\b", s):
        got[1] = part
    if re.search(r"\b(two|second|2nd|#?2)\b", s):
        got[2] = part
    return got or {0: part}


def training_bonuses(adj_vals, names, week: dt.date, aliases: dict = None) -> dict:
    """{name: '#1 and #2' | '#1' | ... | 'None'} paid in weeks BEFORE `week`."""
    got = {n: {} for n in names}
    for r in adj_vals[1:]:
        r = list(r) + [""] * (5 - len(r))
        if str(r[2]).strip().lower() != "bonus":
            continue
        nums = bonus_numbers(r[4])
        if not nums:
            continue
        try:
            if float(str(r[3]).replace("$", "").replace(",", "")) <= 0:
                continue
        except ValueError:
            continue
        wk = week_date(r[0], week)
        if wk is None or wk >= week:
            continue
        for n in names:
            if name_match(n, r[1], aliases):
                for k, v in nums.items():
                    if got[n].get(k) != "full":
                        got[n][k] = v
    out = {}
    for n, g in got.items():
        bits = [f"#{k}" + (" (partial)" if g[k] == "partial" else "") for k in (1, 2) if k in g]
        if not bits and 0 in g:
            bits = ["Yes (no # noted)"]
        out[n] = " and ".join(bits) or "None"
    return out


def _pct(v):
    s = str(v or "").strip()
    try:
        x = float(s.replace("%", ""))
    except ValueError:
        return None
    return x / 100 if "%" in s or x > 1.5 else x


def base_rates(rates_vals) -> dict:
    """{lower name: effective rate} off the Rates tab (col D, as the engine's
    exact-name VLOOKUP reads it)."""
    out = {}
    for r in rates_vals[1:]:
        r = list(r) + [""] * (4 - len(r))
        rate = _pct(r[3])
        if str(r[0]).strip() and rate is not None:
            out.setdefault(str(r[0]).strip().lower(), rate)
    return out


def week_rate(label):
    """The % named by a weekly pay-level row: '45% pay - 10 apps last week',
    'Paid at 30% (Carlos 11/24)'. None for every other label."""
    s = re.sub(r"\([^)]*\)", " ", str(label or "")).lower()
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*% pay\b", s) or re.search(r"\bpaid at (\d+(?:\.\d+)?)\s*%", s)
    return float(m.group(1)) / 100 if m else None


def rates_for(reps, rates_vals, adj_vals, week: dt.date, aliases: dict = None) -> dict:
    """{rep: rate paid this week}: the Rates tab (40% when not on it), beaten by
    this week's pay-level row; a no-pay week reads 0."""
    base = base_rates(rates_vals)
    out = {n: base.get(str(n).strip().lower(), 0.4) for n in reps}
    for r in adj_vals[1:]:
        r = list(r) + [""] * (5 - len(r))
        if week_date(r[0], week) != week:
            continue
        kind = str(r[2]).strip().lower()
        for n in reps:
            if str(r[1]).strip().lower() != str(n).strip().lower() and not name_match(n, r[1], aliases):
                continue
            if kind == "removeall":
                out[n] = 0.0
            elif kind == "bonus" and week_rate(r[4]) is not None:
                out[n] = week_rate(r[4])
    return out


LEVELS = ((14, 0.50), (10, 0.45))            # apps Mon-Sun -> leader rate (Carlos 11/20, 11/24)


def levels_due(board_vals, weekdata_vals, week: dt.date) -> dict:
    """{board name: (apps, rate)} for every Level 1+ rep whose Mon-Sun apps in
    the pay week reach a level. board_vals starts at the header row."""
    hdr = [str(c).strip() for c in board_vals[0]]
    cn, cl = hdr.index("REP"), hdr.index("Leadership Status")
    keys = {f"{week.month}.{week.day}", f"{week.month}.{week.day:02d}"}
    apps = {}
    for r in weekdata_vals:
        if "|" not in str(r[0] if r else ""):
            continue
        name, wk = str(r[0]).rsplit("|", 1)
        if wk.strip() in keys:
            apps[name.strip().lower()] = sum(int(float(x)) for x in r[1:8]
                                             if re.match(r"^\s*\d+(\.0)?\s*$", str(x)))
    out = {}
    for r in board_vals[1:]:
        r = [str(c).strip() for c in r] + [""] * (len(hdr) - len(r))
        if not r[0].isdigit() or r[cl] not in ("Level 1", "Level 2", "Mastermind"):
            continue
        n = apps.get(r[cn].lower(), 0)
        for need, rate in LEVELS:
            if n >= need:
                out[r[cn]] = (n, rate)
                break
    return out


def levels_report(due: dict, paid: dict, aliases: dict = None) -> str:
    """'Roseanna 14 apps -> 50% ok; X 12 apps -> 45% NOT APPLIED (40%)'."""
    bits = []
    for name, (n, rate) in sorted(due.items(), key=lambda x: -x[1][0]):
        hit = [p for p in paid if name_match(name, p, aliases)]
        if not hit:
            bits.append(f"{name} {n} apps -> {rate:.0%} (no line this week)")
        elif paid[hit[0]] + 1e-9 >= rate:
            bits.append(f"{name} {n} apps -> {rate:.0%} ok")
        else:
            bits.append(f"{name} {n} apps -> {rate:.0%} NOT APPLIED (paid {paid[hit[0]]:.0%})")
    return "; ".join(bits) or "nobody reached 10 apps"


RATE_HDR = "Rate"
PCT_HDR = "Percentage Payout"
# the itemized block's columns on the raw CS copy (before any column is added)
I_REP, I_SALE, I_DESC, I_CUST, I_AMT, I_COMM = 6, 7, 9, 12, 13, 14


def _num(v):
    s = str(v if v is not None else "").replace("$", "").replace(",", "").strip()
    neg = s.startswith("-") or s.startswith("(")
    try:
        x = float(s.strip("()-") or "nan")
    except ValueError:
        return None
    if x != x:
        return None
    return -x if neg else x


def payout_plan(mat, restate: bool = True) -> dict:
    """What the Percentage Payout step changes, as 0-based rows of `mat`:
      drop  = pay-level bonus rows to take off the sheet,
      comm  = {row: commission at the week's rate},
      pct   = {row: the line's %}  (bonus / Total / header rows have none),
      hdr   = header rows."""
    drop, comm, pct, hdr = [], {}, {}, []
    start = {}                                     # rep -> sale rows
    for i, row in enumerate(mat):
        r = list(row) + [""] * (15 - len(row))
        rep = str(r[I_REP]).strip()
        if rep == "REP Name":
            hdr.append(i)
            continue
        if not rep:
            continue
        sale = bool(str(r[I_SALE]).strip() or str(r[I_CUST]).strip())
        if not sale:
            if restate and week_rate(r[I_DESC]) is not None:
                drop.append(i)
            continue
        start.setdefault(rep, []).append(i)
    dropped = {str(mat[i][I_REP]).strip(): week_rate(mat[i][I_DESC]) for i in drop}
    for rep, rows in start.items():
        for i in rows:
            r = list(mat[i]) + [""] * (15 - len(mat[i]))
            amt, com = _num(r[I_AMT]), _num(r[I_COMM])
            if amt is None or com is None:
                continue
            if rep in dropped and com:                # an unpaid line stays unpaid
                com = round(amt * dropped[rep], 2)
                comm[i] = com
            pct[i] = round(com / amt, 4) if amt else ""
    return {"drop": sorted(drop), "comm": comm, "pct": pct, "hdr": hdr}


def plan_ties(mat, plan: dict) -> bool:
    """The rep's lines at the new % must add up to the same money the pay-level
    bonus row paid; if not (an odd line), nothing is restated."""
    for i in plan["drop"]:
        rep = str(mat[i][I_REP]).strip()
        rows = [k for k in plan["comm"] if str(mat[k][I_REP]).strip() == rep]
        gain = sum(plan["comm"][k] - (_num(mat[k][I_COMM]) or 0) for k in rows)
        if abs(gain - (_num(mat[i][I_COMM]) or 0)) > 0.011:
            return False
    return True


def pct_requests(sid, plan: dict, n_rows: int) -> list:
    """Delete the pay-level rows (itemized columns only, so the rep summary on
    the left never moves), then insert the column right of Total $ to ICD."""
    reqs = [{"deleteRange": {"range": _rng(sid, i, i + 1, I_REP, I_COMM + 1), "shiftDimension": "ROWS"}}
            for i in sorted(plan["drop"], reverse=True)]
    reqs.append({"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": I_COMM,
                                               "endIndex": I_COMM + 1}, "inheritFromBefore": True}})
    reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                         "startIndex": I_COMM, "endIndex": I_COMM + 1},
                                               "properties": {"pixelSize": 145}, "fields": "pixelSize"}})
    reqs.append({"repeatCell": {"range": _rng(sid, 2, n_rows, I_COMM, I_COMM + 1),
                                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"},
                                                               "horizontalAlignment": "CENTER"}},
                                "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
    return reqs


def add_payout_column(sh, ws, mat, *, log) -> dict:
    plan = payout_plan(mat)
    if not plan["hdr"]:
        return {}
    if not plan_ties(mat, plan):
        log("commission sheet: pay-level lines do not tie to their bonus row -- left as bonus lines")
        plan = payout_plan(mat, restate=False)
    gone = sorted(plan["drop"])

    def shifted(i):
        return i - sum(1 for d in gone if d < i)
    sh.batch_update({"requests": pct_requests(ws.id, plan, ws.row_count)})
    data = [{"range": f"O{shifted(i) + 1}", "values": [[PCT_HDR]]} for i in plan["hdr"]]
    data += [{"range": f"O{shifted(i) + 1}", "values": [[v]]} for i, v in plan["pct"].items()]
    data += [{"range": f"P{shifted(i) + 1}", "values": [[v]]} for i, v in plan["comm"].items()]
    ws.batch_update(data, value_input_option="RAW")
    odd = [shifted(i) for i, v in plan["pct"].items()
           if isinstance(v, float) and abs(v * 100 - round(v * 100)) > 0.001]
    if odd:                                                # 37.5% and the like
        sh.batch_update({"requests": [{"repeatCell": {
            "range": _rng(ws.id, k, k + 1, I_COMM, I_COMM + 1),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}},
            "fields": "userEnteredFormat.numberFormat"}} for k in odd]})
    log(f"commission sheet: Percentage Payout added ({len(plan['pct'])} lines, {len(gone)} pay-level row(s) "
        f"shown as a % instead of a bonus)")
    return plan


_GRID = {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}}
_EDGE = {"style": "SOLID_MEDIUM", "color": {"red": 0.4, "green": 0.4, "blue": 0.4}}


def rate_requests(sid, total_row: int) -> list:
    """Insert column E (Rate) on the CS copy: summary rows 3..TOTAL keep their
    grid over A:F, the old empty F becomes the G spacer."""
    top = 2                                         # row 3, 0-based
    return [
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
                             "inheritFromBefore": False}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
                                       "properties": {"pixelSize": 70}, "fields": "pixelSize"}},
        {"repeatCell": {"range": _rng(sid, top, total_row + 1, 4, 5),
                        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER",
                                                       "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                                       "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                        "fields": "userEnteredFormat(horizontalAlignment,backgroundColor,numberFormat)"}},
        {"repeatCell": {"range": _rng(sid, top, top + 1, 4, 5),
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"updateBorders": {"range": _rng(sid, top, total_row + 1, 0, 6), "top": _EDGE, "bottom": _EDGE,
                           "left": _EDGE, "right": _EDGE, "innerHorizontal": _GRID, "innerVertical": _GRID}},
        {"updateBorders": {"range": _rng(sid, top, top + 1, 0, 6), "bottom": _EDGE}},
    ]


def gap_requests(sid, row_count: int, col: int) -> list:
    """The empty column between the itemized block and the Brought In box has
    no lines of its own (Carlos 11/24: "fix these random lines on column R").
    The block's right edge and the box's left edge belong to their own cells."""
    return [{"updateBorders": {"range": _rng(sid, 0, row_count, col, col + 1), "top": _NONE, "bottom": _NONE,
                               "innerHorizontal": _NONE}},
            {"updateBorders": {"range": _rng(sid, 0, 2, col, col + 1), "left": _NONE}}]


def add_rate_column(sh, ws, mat, week: dt.date, *, log) -> dict:
    panels = find_panels(mat)
    t = panels["total"]
    if t is None or len(mat[2]) < 5 or str(mat[2][4]).strip() == RATE_HDR:
        return {}
    reps = [str(mat[i][0]).strip() for i in range(3, t)]
    al = _alias_map(sh)
    rates = rates_for([r for r in reps if r], sh.worksheet("Rates").get_all_values(),
                      sh.worksheet("Adjustments").get_all_values(), week, al)
    sh.batch_update({"requests": rate_requests(ws.id, t)})
    sh.batch_update({"requests": gap_requests(ws.id, ws.row_count, 17)})      # R, after both new columns
    ws.update(range_name=f"E3:E{t}", values=[[RATE_HDR]] + [[rates.get(r, "")] for r in reps],
              value_input_option="RAW")
    log(f"commission sheet: Rate column added ({len(reps)} reps)")
    try:
        due = levels_due(sh.worksheet("NDS Sales Board").get("A4:Q40"),
                         sh.worksheet("WeekData").get_all_values(), week)
        log("pay levels: " + levels_report(due, rates, al))
    except Exception as e:  # noqa: BLE001 -- a report, never a blocker
        log(f"pay levels: not checked ({type(e).__name__}: {e})")
    return rates


def find_panels(mat) -> dict:
    """0-based rows of the summary TOTAL and the three panels under it."""
    def cell(i, j):
        return str(mat[i][j]).strip() if i < len(mat) and j < len(mat[i]) else ""

    def run(start, col):
        n = 0
        while cell(start + n, col):
            n += 1
        return n

    p = {"total": None, "norev": None, "revnot": None, "fs": None}
    for i in range(2, len(mat)):
        a = cell(i, 0)
        if p["total"] is None and a == "TOTAL":
            p["total"] = i
        elif p["total"] is not None and a == NO_REV:
            p["norev"] = (i, run(i + 1, 0))
        elif p["total"] is not None and a == FIRST_SECOND:
            p["fs"] = (i, run(i + 2, 0))
        if p["total"] is not None and cell(i, 2) == REV_NOT and p["revnot"] is None:
            p["revnot"] = (i, run(i + 1, 2))
    return p


_MED = {"style": "SOLID_MEDIUM", "color": {"red": 0, "green": 0, "blue": 0}}
_NONE = {"style": "NONE"}


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _box(sid, r0, r1, c0, c1):
    return {"updateBorders": {"range": _rng(sid, r0, r1, c0, c1), "top": _MED, "bottom": _MED,
                              "left": _MED, "right": _MED, "innerHorizontal": _MED}}


def border_requests(sid, panels, row_count, *, fs_cols: int, cols: int = 5) -> list:
    """Wipe the borders under TOTAL (A:E, or A:F with a Rate column), then
    redraw only the three panels."""
    t = panels["total"]
    if t is None or t + 1 >= row_count:
        return []
    reqs = [{"updateBorders": {"range": _rng(sid, t + 1, row_count, 0, cols), "bottom": _NONE,
                               "left": _NONE, "right": _NONE, "innerHorizontal": _NONE,
                               "innerVertical": _NONE}}]
    if panels["norev"] and panels["norev"][1]:
        i, n = panels["norev"]
        reqs.append(_box(sid, i, i + 1 + n, 0, 1))
    if panels["revnot"] and panels["revnot"][1]:
        i, n = panels["revnot"]
        reqs.append(_box(sid, i, i + 1 + n, 2, 4))
    if panels["fs"]:
        i, n = panels["fs"]
        reqs.append(_box(sid, i, i + 2 + n, 0, fs_cols))
    return reqs


def fs_requests(sid, panels) -> list:
    """Column D of the FIRST & SECOND table: C's look, title merged A:D."""
    if not panels["fs"]:
        return []
    i, n = panels["fs"]
    return [
        {"unmergeCells": {"range": _rng(sid, i, i + 1, 0, 5)}},
        {"copyPaste": {"source": _rng(sid, i, i + 2 + n, 2, 3),
                       "destination": _rng(sid, i, i + 2 + n, 3, 4),
                       "pasteType": "PASTE_FORMAT"}},
        {"mergeCells": {"range": _rng(sid, i, i + 1, 0, 4), "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": _rng(sid, i + 2, i + 2 + max(n, 1), 1, 3),
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": _rng(sid, i + 1, i + 2 + n, 3, 4),
                        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)"}},
    ]


def _alias_map(sh) -> dict:
    out = {}
    for r in sh.worksheet("Name Aliases").get_all_values()[1:]:
        if len(r) > 1 and r[0].strip() and r[1].strip():
            out[r[0].strip().lower()] = r[1].strip()
    return out


def finish_cs(sh, ws, mat, week: dt.date, *, log) -> dict:
    """Fill the FIRST & SECOND table and clean the borders on one CS tab."""
    panels = find_panels(mat)
    rows = ws.row_count
    if panels["total"] is None:
        log("commission sheet: no TOTAL row found, left as is")
        return {}
    filled = {}
    fs_ok = False
    if panels["fs"]:
        i, n = panels["fs"]
        names = [str(mat[i + 2 + k][0]).strip() for k in range(n)]
        if names:
            al = _alias_map(sh)
            counts = order_counts(sh.worksheet("NDS Order Log").get_all_values(), names, week, al)
            bons = training_bonuses(sh.worksheet("Adjustments").get_all_values(), names, week, al)
            filled = {nm: (*counts[nm], bons[nm]) for nm in names}
        sh.batch_update({"requests": fs_requests(ws.id, panels)})
        ws.update(range_name=f"A{i + 2}:D{i + 2 + n}",
                  values=[["Rep", "Order Count", "Total Apps", BONUS_HDR]]
                  + [[nm, *filled[nm]] for nm in names], value_input_option="RAW")
        fs_ok = True
    sh.batch_update({"requests": border_requests(ws.id, panels, rows, fs_cols=4 if fs_ok else 3)})
    log(f"commission sheet: first/second-week table {filled}; borders cleaned below TOTAL")
    return filled


def clean_borders(sh, ws, *, log) -> bool:
    """Borders only, for CS tabs already snapped (no values touched)."""
    mat = ws.get("A1:E")
    panels = find_panels(mat)
    if panels["total"] is None:
        log(f"{ws.title}: no TOTAL row found, left as is")
        return False
    fs_cols = 3
    if panels["fs"]:
        hdr = mat[panels["fs"][0] + 1]
        fs_cols = 4 if len(hdr) > 3 and str(hdr[3]).strip() == BONUS_HDR else 3
    cols = 6 if len(mat) > 2 and len(mat[2]) > 4 and str(mat[2][4]).strip() == RATE_HDR else 5
    reqs = border_requests(ws.id, panels, ws.row_count, fs_cols=fs_cols, cols=cols)
    if reqs:
        sh.batch_update({"requests": reqs})
    return bool(reqs)
