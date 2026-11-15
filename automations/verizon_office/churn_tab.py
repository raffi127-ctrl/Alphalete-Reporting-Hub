"""The "VERIZON CHURN" tab on the Vantura Master Sales Board -- Nico's office,
the NDS CHURN tab's shape (nds_churn/sheet.py), on Credico's terms.

Carlos 2026-11-15: "NDS has this NDS churn tab ... can we make one for
Verizon as well? ... find out what the term numbers are that determine the
tier, the payout, and everything."

THE TERMS live in verizon_office/comp.py, read off the Credico PDFs Nico
forwarded to the review group on 2026-11-07 (Verizon Wireless SOW Schedule A
6.16.26, Churn Schedule Wireless 2026 v1.13.26, Activation Bonus, AutoPay
Bonus): eight churn tiers on the office's 30-day churn (0-4.99% = Tier 1
$237 per new port line ... 34%+ = Tier 8 $127), measured over a fixed
30-day window per 4-week block of sales weeks (comp.CHURN_CALENDAR), Tier 4
neutral under 15 activations; every other line (new no-port, CPO, BYOD) a
flat $25; AutoPay +$60, Unlimited Plus / Ultimate +$35, Mobile Protect /
Secure +$35; the weekly activation bonus by unique orders (4 / 5-6 / 7-8 /
9+ -> $30 / $50 / $75 / $110 a line), a rep at 40%+ 90-day cancels
disqualified. Credico's own notice is the official placement; this tab shows
where the live number lands.

WHAT THE TAB SHOWS (one Credico Order Detail pull, same as the Order Log):
  * the top-left box: lines ACTIVATED in the last 30 days (rolling, by
    activation date) and how many of those have DISCONNECTED = churn %, for
    All Lines / Port (non-BYOD) / BYOD / New (non-BYOD), with pending counts
    and the 0-30 / 31-60 day activation rates (sold by order-date age,
    activated = active now or disconnected after activating -- the NDS rule);
  * the Credico tier chart, the live band marked "◀ now" off the calendar
    window Credico actually scores (comp.office_tier), and a status line
    with the window, its rate and the rules;
  * the 0-30 day rolloff list as stacked tables (Port non-BYOD / BYOD /
    New), one row per disconnected line, soonest to fall off first: Days
    Left = (Activation Date + 30) - today, and what the churn % becomes once
    that line has aged off;
  * the per-rep 0-30 day activation rate list on the right.

Customer names are on this tab (the Vantura Master is Carlos's own workbook,
like the NDS CHURN tab). Nothing here posts to Slack.

SANDBOX FIRST (Eve's rule): a bare --write goes to the Sales Board SANDBOX
copy; --prod / daily.CHURN_TAB_PROD = True is the Vantura Master.

    python -m automations.verizon_office.churn_tab --office nicolas            # dry run: prints the box + rolloff
    python -m automations.verizon_office.churn_tab --sv FILE.xlsx
    python -m automations.verizon_office.churn_tab --office nicolas --write    # sandbox
    python -m automations.verizon_office.churn_tab --office nicolas --write --prod
    lucy rerun verizon_churn_tab -- --write

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.verizon_office import comp as C
from automations.verizon_office import order_log_tab as OL

ROOT = Path(__file__).resolve().parents[2]
PROD_SHEET_ID = OL.PROD_SHEET_ID
SANDBOX_SHEET_ID = OL.SANDBOX_SHEET_ID
TAB = "VERIZON CHURN"
PROTECTED_TABS = OL.PROTECTED_TABS + ("NDS CHURN", "LUCY CHURN", "Verizon Order Log")
WINDOW_DAYS = 30
TITLE = "VERIZON — 0–30 Day Rolloff List — soonest to fall off"
SOURCE = ("Verizon Wireless SOW Schedule A 6.16.26 + Churn Schedule Wireless 2026 (v1.13.26), "
          "Credico PDFs Nico forwarded 11/7 (comp.py)")

CLASSES = ("port", "byod", "new")
CLASS_TITLES = {"port": "PORT (non-BYOD)", "byod": "BYODs", "new": "NEW (non-BYOD)"}
BOX_ROWS = (("All Lines", None), ("Port (non-BYOD)", "port"), ("BYOD", "byod"), ("New (non-BYOD)", "new"))
LIST_HEADERS = ("Days Left", "Fall-Off Date", "Lines", "All Lines % After Rolloff", "% After Rolloff",
                "Customer", "Sales Rep", "Order Date", "Activation Date", "Disconnect Date",
                "Port / New", "Device", "Plan", "Status Reason")
# Credico's tier bands, best first, as the SOW prints them (comp.CHURN_TIERS ceilings)
TIER_LABELS = {1: "0 – 4.99%", 2: "5 – 6.99%", 3: "7 – 8.99%", 4: "9 – 14.99%", 5: "15 – 19.99%",
               6: "20 – 26.99%", 7: "27 – 33.99%", 8: "34%+"}


# ------------------------------------------------------------ the lines ----

def _d(s) -> Optional[dt.date]:
    return OL._d(s)


def line_class(l: Dict[str, str]) -> str:
    dev = (l.get("Device") or "").strip().upper()
    if dev == "BYOD":
        return "byod"
    return "port" if l.get("Type") == "Port" else "new"


def is_dead(l) -> bool:
    return (l.get("Line Status") or "").lower() == "disconnected"


def is_activated(l) -> bool:
    """Active now, or disconnected after activating (it was active first)."""
    return (l.get("Line Status") or "").lower() in ("active", "disconnected") and bool(_d(l.get("Activation Date")))


def churn_units(lines, today: dt.date, days: int = WINDOW_DAYS) -> List[Dict[str, str]]:
    """Lines ACTIVATED inside the rolling window (activation date within the
    last `days` days, today included)."""
    cutoff = today - dt.timedelta(days=days)
    out = []
    for l in lines:
        a = _d(l.get("Activation Date"))
        if a and cutoff <= a <= today and is_activated(l):
            out.append(l)
    return out


def churn_summary(lines, today: dt.date) -> Dict[str, dict]:
    """{row label: {base, disc, rate, pending}} for the box rows. Pending =
    sold in the last 30 days, not activated, not cancelled."""
    units = churn_units(lines, today)
    cutoff = today - dt.timedelta(days=WINDOW_DAYS)
    out = {}
    for label, cls in BOX_ROWS:
        mine = [u for u in units if cls is None or line_class(u) == cls]
        disc = sum(1 for u in mine if is_dead(u))
        pend = sum(1 for l in lines if (cls is None or line_class(l) == cls)
                   and not _d(l.get("Activation Date"))
                   and (l.get("Line Status") or "").lower() not in ("cancelled", "canceled", "disconnected")
                   and _d(l.get("Order Date")) and cutoff <= _d(l.get("Order Date")) <= today)
        out[label] = {"base": len(mine), "disc": disc,
                      "rate": (disc / len(mine)) if mine else None, "pending": pend}
    return out


def activation_rates(lines, today: dt.date) -> Tuple[dict, dict]:
    """(office, reps): {'0-30': {activated, sold, rate}, '31-60': {...}} by
    ORDER-date age, activated = is_activated (the NDS Activation Rate rule)."""
    def _blank():
        return {b: {"activated": 0, "sold": 0, "rate": None} for b in ("0-30", "31-60")}
    office, reps = _blank(), {}
    for l in lines:
        od = _d(l.get("Order Date"))
        if not od:
            continue
        age = (today - od).days
        b = "0-30" if 0 <= age <= 30 else "31-60" if 31 <= age <= 60 else None
        if b is None:
            continue
        for slot in (office[b], reps.setdefault(l.get("Rep") or "(no rep)", _blank())[b]):
            slot["sold"] += 1
            if is_activated(l):
                slot["activated"] += 1
    for d in [office] + list(reps.values()):
        for b in ("0-30", "31-60"):
            s = d[b]
            s["rate"] = (s["activated"] / s["sold"]) if s["sold"] else None
    return office, reps


def rolloff_rows(lines, today: dt.date) -> Dict[str, List[dict]]:
    """{class: [row dicts soonest to fall off first]}. Every disconnected line
    in the 0-30 window; '% After Rolloff' = the churn % once this line AND
    every line activated on or before it have aged off (all lines, and the
    line's own class)."""
    units = churn_units(lines, today)
    out: Dict[str, List[dict]] = {c: [] for c in CLASSES}

    def pct_after(scope_units, posted: dt.date) -> Optional[float]:
        left = [u for u in scope_units if _d(u["Activation Date"]) > posted]
        if not left:
            return 0.0
        return sum(1 for u in left if is_dead(u)) / len(left)

    by_cls = {c: [u for u in units if line_class(u) == c] for c in CLASSES}
    for u in sorted((u for u in units if is_dead(u)),
                    key=lambda u: (_d(u["Activation Date"]), u.get("Customer", ""))):
        posted = _d(u["Activation Date"])
        cls = line_class(u)
        falloff = posted + dt.timedelta(days=WINDOW_DAYS)
        out[cls].append({
            "days_left": (falloff - today).days, "falloff": falloff, "lines": 1,
            "pct_all": pct_after(units, posted), "pct_cls": pct_after(by_cls[cls], posted),
            "customer": u.get("Customer", ""), "rep": u.get("Rep", ""),
            "order_date": _d(u.get("Order Date")), "posted": posted, "disc_date": _d(u.get("Cancel Date")),
            "kind": "port" if u.get("Type") == "Port" else "new",
            "device": u.get("Device", ""), "plan": u.get("Plan", ""), "reason": u.get("Status Reason", ""),
        })
    return out


def credico_tier(sv_path: Path, today: dt.date) -> dict:
    """Where the office sits on Credico's calendar window (comp.office_tier):
    {tier, why, window: (w0, w1) or None, pay}."""
    L = C.lines(sv_path)
    tier, why = C.office_tier(L, today)
    start, _ = C.sales_week(today)
    block = [c for c in C.CHURN_CALENDAR if c[0] <= start]
    window = (block[-1][1], block[-1][2]) if block else None
    return {"tier": tier, "why": why, "window": window, "pay": C.PORT_TIER_PAY[tier]}


# ------------------------------------------------------------ the sheet ----

def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def _pct(v: Optional[float]) -> str:
    return "" if v is None else "%.2f%%" % (v * 100)


def _rate(v: Optional[float]) -> str:
    return "" if v is None else "%.1f%%" % (v * 100)


def build_grid(lines, today: dt.date, tier: dict) -> Tuple[List[List[str]], dict]:
    """The whole tab as a grid of strings plus the row/col map the formatter
    needs. Columns A:N = box + rolloff tables, P:Q = the rep list."""
    summary = churn_summary(lines, today)
    office, reps = activation_rates(lines, today)
    roll = rolloff_rows(lines, today)
    W = 17                                                     # A..Q
    g: List[List[str]] = []

    def row(vals=(), at=None):
        r = [""] * W
        for i, v in enumerate(vals):
            r[(at or 0) + i] = str(v)
        g.append(r)
        return len(g)                                          # 1-based row number

    marks = {"bands": [], "headers": [], "churn_cells": [], "rate_cells": [], "dead_rows": []}
    row([TITLE])
    row(["Days left = (Activation Date + 30) − Today. Box = lines activated in the last 30 days and how many "
         "have disconnected since; activation rates by order-date age (activated = active now, or disconnected after activating)."])
    row()
    hdr = row(["Product", "Activations", "Disconnects", "Churn %", "0-30 Day Activation Rate", "31-60 Day Activation Rate"])
    marks["headers"].append(hdr)
    # tier chart header on the right of the box (H..K)
    g[hdr - 1][7:11] = ["Credico Tier", "0-30 Day Churn", "$ / new port line", ""]
    tier_rows = []
    for label, cls in BOX_ROWS:
        s = summary[label]
        r = row([label, s["base"], s["disc"], _pct(s["rate"]),
                 _rate(office["0-30"]["rate"]) if cls is None else "",
                 _rate(office["31-60"]["rate"]) if cls is None else ""])
        marks["churn_cells"].append((r, 3, s["rate"]))
        if cls is None:
            marks["rate_cells"].append((r, 4, office["0-30"]["rate"]))
        row([label + " Pending", s["pending"]])
    # the eight tiers, written beside the box rows (rows hdr+1 .. hdr+8)
    for t in range(1, 9):
        rr = hdr + t
        while len(g) < rr:
            row()
        mark = "◀ now" if t == tier["tier"] else ""
        g[rr - 1][7:11] = ["Tier %d" % t, TIER_LABELS[t], "$%d" % C.PORT_TIER_PAY[t], mark]
        tier_rows.append(rr)
    row()
    w = tier["window"]
    win = "%d/%d–%d/%d" % (w[0].month, w[0].day, w[1].month, w[1].day) if w else "n/a"
    row(["Credico window %s: %s → $%d per new port line. Flat $25 for new no-port / CPO / BYOD; AutoPay +$60; "
         "Unlimited Plus / Ultimate +$35; Mobile Protect / Secure +$35. Weekly bonus by unique orders 4 / 5–6 / 7–8 / 9+ "
         "→ $30 / $50 / $75 / $110 a line; a rep at 40%%+ 90-day cancels is DNQ. Tier 4 neutral under 15 activations. "
         "Source: %s." % (win, tier["why"], tier["pay"], SOURCE)])
    row()
    # the rolloff tables + the rep list, side by side
    rep_top = len(g) + 1
    for cls in CLASSES:
        s = summary[{"port": "Port (non-BYOD)", "byod": "BYOD", "new": "New (non-BYOD)"}[cls]]
        b = row(["%s — churn %s (%d of %d activated in the last 30 days disconnected)"
                 % (CLASS_TITLES[cls], _pct(s["rate"]) or "0.00%", s["disc"], s["base"])])
        marks["bands"].append(b)
        h = row(list(LIST_HEADERS[:4]) + ["%s %s" % (CLASS_TITLES[cls], LIST_HEADERS[4])] + list(LIST_HEADERS[5:]))
        marks["headers"].append(h)
        for x in roll[cls]:
            r = row(["%dd" % x["days_left"], _fmt(x["falloff"]), x["lines"], _pct(x["pct_all"]), _pct(x["pct_cls"]),
                     x["customer"], x["rep"], _fmt(x["order_date"]), _fmt(x["posted"]), _fmt(x["disc_date"]),
                     x["kind"], x["device"], x["plan"], x["reason"]])
            marks["dead_rows"].append(r)
        if not roll[cls]:
            row(["(no disconnects in the 0-30 window)"])
        row()
    # rep list in P:Q from rep_top
    rep_rows = [("OFFICE TOTAL (all reps)", office["0-30"]["rate"], office["0-30"]["activated"], office["0-30"]["sold"])]
    rep_rows += sorted(((r, v["0-30"]["rate"], v["0-30"]["activated"], v["0-30"]["sold"]) for r, v in reps.items()
                        if v["0-30"]["sold"]), key=lambda t: (-(t[1] or 0), t[0].lower()))
    need = rep_top + len(rep_rows) + 1
    while len(g) < need:
        row()
    g[rep_top - 1][15:17] = ["Rep Name", "0-30 Day Activation Rate"]
    marks["headers"].append(rep_top)
    for k, (name, rate, a, n) in enumerate(rep_rows, 1):
        g[rep_top - 1 + k][15:17] = [name, "%s  (%d/%d)" % (_rate(rate), a, n)]
        marks["rate_cells"].append((rep_top + k, 16, rate))
    marks["tier_rows"] = tier_rows
    marks["n_rows"] = len(g)
    return g, marks


def _format_requests(sheet_id: int, marks: dict) -> List[dict]:
    from automations.office_metrics.nds_orderlog import _ACT_BANDS
    NAVY, DARK, WHITE = (0.12, 0.23, 0.37), (0.24, 0.24, 0.24), (1, 1, 1)
    GREEN, YELLOW, RED = (0.776, 0.937, 0.808), (1, 0.949, 0.8), (1, 0.78, 0.808)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    def fill(r0, r1, c0, c1, rgb, bold=False, fg=None):
        fmt = {"backgroundColor": {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}, "horizontalAlignment": "CENTER"}
        if bold or fg:
            fmt["textFormat"] = {"bold": bold, "foregroundColor": {"red": (fg or (0, 0, 0))[0], "green": (fg or (0, 0, 0))[1], "blue": (fg or (0, 0, 0))[2]}}
        return {"repeatCell": {"range": rng(r0, r1, c0, c1), "cell": {"userEnteredFormat": fmt},
                               "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}}
    n = max(marks["n_rows"], 60)
    reqs = [
        {"repeatCell": {"range": rng(0, n, 0, 17), "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}, "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment)"}},
        {"mergeCells": {"range": rng(0, 1, 0, 14), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(1, 2, 0, 14), "mergeType": "MERGE_ALL"}},
        fill(0, 1, 0, 14, NAVY, True, WHITE),
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 2}}, "fields": "gridProperties.frozenRowCount"}},
    ]
    for r in marks["headers"]:
        reqs.append(fill(r - 1, r, 0, 17, NAVY, True, WHITE))
    for r in marks["bands"]:
        reqs.append({"mergeCells": {"range": rng(r - 1, r, 0, 14), "mergeType": "MERGE_ALL"}})
        reqs.append(fill(r - 1, r, 0, 14, DARK, True, WHITE))
    for r in marks["tier_rows"]:
        t = r - marks["tier_rows"][0] + 1
        rgb = GREEN if t <= 3 else YELLOW if t <= 5 else RED
        reqs.append(fill(r - 1, r, 8, 9, rgb))
    for r, c, v in marks["churn_cells"]:
        if v is None:
            continue
        reqs.append(fill(r - 1, r, c, c + 1, GREEN if v < 0.07 else YELLOW if v < 0.15 else RED, True))
    for r, c, v in marks["rate_cells"]:
        if v is None:
            continue
        color = next(col for floor, col in _ACT_BANDS["0-30 Day"] if v >= floor)
        reqs.append(fill(r - 1, r, c, c + 1, {"Green": GREEN, "Yellow": YELLOW, "Red": RED}[color]))
    for r in marks["dead_rows"]:
        reqs.append(fill(r - 1, r, 0, 14, RED))
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 17}}})
    for c, px in ((0, 90), (3, 190), (4, 220), (5, 170), (6, 200), (11, 160), (12, 150), (13, 300), (15, 230), (16, 200)):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


def push(sv_path: Path, *, today: Optional[dt.date] = None, sheet_id: str = SANDBOX_SHEET_ID, log=print) -> dict:
    from automations.recruiting_report.fill import _retry, open_by_key
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    today = today or dt.date.today()
    lines = OL.lines(Path(sv_path))
    tier = credico_tier(Path(sv_path), today)
    grid, marks = build_grid(lines, today, tier)
    sh = open_by_key(sheet_id)
    ws = OL._ensure_tab(sh, TAB, cols=17)
    _retry(lambda: ws.resize(rows=max(200, len(grid) + 20), cols=17))
    _retry(lambda: ws.clear())
    _retry(lambda: sh.batch_update({"requests": [{"unmergeCells": {"range": {"sheetId": ws.id}}}]}))
    _retry(lambda: ws.update(grid, "A1", value_input_option="USER_ENTERED"))
    _retry(lambda: sh.batch_update({"requests": _format_requests(ws.id, marks)}))
    s = churn_summary(lines, today)["All Lines"]
    where = "PROD" if sheet_id == PROD_SHEET_ID else "sandbox"
    log("[verizon] %s tab (%s): %d activated / %d disconnected in the last 30 days (%s), Credico %s"
        % (TAB, where, s["base"], s["disc"], _pct(s["rate"]) or "0%", tier["why"]))
    return {"rows": len(grid), "summary": s, "tier": tier}


def refresh(sv_path: Path, *, today: Optional[dt.date] = None, prod: bool = False, log=print) -> dict:
    return push(Path(sv_path), today=today, sheet_id=PROD_SHEET_ID if prod else SANDBOX_SHEET_ID, log=log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--sv", type=Path)
    ap.add_argument("--date")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--prod", action="store_true")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sv = a.sv
    if not sv:
        from automations.verizon_office import offices as OF, run as RUN
        sv = RUN.fetch(OF.get(a.office), "sales")
        if not sv:
            print("✗ no Sales Verification in the Hub inbox -- is the office's Outlook rule delivering?")
            return 1
    sv = Path(sv)
    if not a.write:
        lines = OL.lines(sv)
        tier = credico_tier(sv, today)
        for label, s in churn_summary(lines, today).items():
            print("  %-18s activated %3d  disconnected %3d  churn %-8s pending %d" % (label, s["base"], s["disc"], _pct(s["rate"]) or "0%", s["pending"]))
        print("  Credico: %s -> $%d per new port line" % (tier["why"], tier["pay"]))
        roll = rolloff_rows(lines, today)
        print("  rolloff rows: %s" % {c: len(v) for c, v in roll.items()})
        print("DRY RUN -- nothing written")
        return 0
    push(sv, today=today, sheet_id=PROD_SHEET_ID if a.prod else SANDBOX_SHEET_ID)
    return 0


if __name__ == "__main__":
    sys.exit(main())
