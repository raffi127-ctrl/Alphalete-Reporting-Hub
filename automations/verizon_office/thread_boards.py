"""Nico's Verizon metrics on the SAME boards every NDS wireless office gets.

    python -m automations.verizon_office.thread_boards --sv FILE.xlsx [--date YYYY-MM-DD]

Megan 2026-11-07: "mirror what we do for the other programs - we want it all
as systematic as we can". NDS (office_metrics.runner._nds_metrics) is the
wireless thread: Rep Activations, Pending Orders, Activation Rate by Rep,
Order Log (.xlsx, a tab per rep), Canceled Orders, Disconnected Orders. This
module does NOT draw any of them. It turns Credico's Sales Verification
'Order Detail' into the NDS ORDER LOG's columns and hands that to
nds_orderlog's own renderers, so a column added there shows up here too.

Credico -> NDS, one row per WIRELESS LINE (Product Category = Wireless Line):
  DTR Status   Activated (has an Activation Date)  -> Posted
               Status Code CAN + Disc. (Pre/Post)  -> Disconnected
               Status Code CAN otherwise           -> Canceled
               Status Code REJ (Incomplete etc.)   -> Canceled (never a sale)
               everything else (Submitted)         -> its own status = pending
  Order Date = Signed Date · Status Date = Cancel Date, else Activation Date
  Package    = the order's Base Plan · Device = Item Desc · TN Type = port/new

NO CUSTOMER NAMES OR NUMBERS: Customer Name and Phone go out blank (Order
Detail has names; Credico carries no line number we post). Counts, plan,
device and Credico's order number only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

ROOT = Path(__file__).resolve().parents[2]

# The NDS ORDER LOG column names nds_orderlog._find() looks for.
HEADER = ["Rep", "DTR Status", "spe.Status", "sp.Order Date", "Status Date",
          "DTR Active Date", "sp.SPM Number", "spe.Name", "spe.TN",
          "Customer Name", "Package", "Product Type", "spe.Wireless Type",
          "spe.TN Type", "spe.Port Carrier", "Measure Names"]


def _d(v) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def _us(d: Optional[dt.date]) -> str:
    return f"{d.month:02d}/{d.day:02d}/{d.year}" if d else ""


def _rep(name) -> str:
    return " ".join(str(name or "").split())


def _plan(name) -> str:
    # "Unlimited Welcome - New" -> "Unlimited Welcome"
    s = str(name or "").strip()
    for tail in (" - New", " - Byod", " - Cpo"):
        if s.endswith(tail):
            s = s[: -len(tail)]
    # "Verizon Simplicity Plan (Smartphone)" -> "Simplicity Plan": the board
    # is already Verizon and every line is a smartphone line.
    s = s.replace(" (Smartphone)", "")
    return s[len("Verizon "):] if s.startswith("Verizon ") else s


def dtr_status(code: str, line_status: str, activated: Optional[dt.date]) -> str:
    code, line_status = (code or "").upper(), (line_status or "")
    if code == "CAN":
        return "Disconnected" if line_status.lower().startswith("disc") else "Canceled"
    if code == "REJ":
        return "Canceled"
    if activated:
        return "Posted"
    return line_status or "Pending"


def nds_rows(sv_path: Path, date_col: str = "Activation Date") -> Tuple[List[str], List[List[str]]]:
    """(HEADER, rows) — Order Detail's wireless lines in NDS ORDER LOG shape."""
    ws = openpyxl.load_workbook(sv_path, data_only=True, read_only=True)["Order Detail"]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next(i for i, r in enumerate(rows) if r and "Sales Agent Name" in r)
    # FIRST column of a name wins, like order_log_tab._find. A dict
    # comprehension kept the LAST: Credico's Order Detail repeats "LineID"
    # and the second copy is mostly blank -- lines with a blank id all keyed
    # (order, "") and one approved line approved its whole order
    # (Churn Rates by Rep 30/366 vs the tab's 23/324, 2026-11-15).
    # ... and by NORMALISED name (case / spaces dropped), exactly order_log_tab
    # ._find: the populated id column is "Line ID" and an exact "LineID" match
    # still found the blank copy (churn_diag 20:56, after the first-wins fix).
    def _norm(h) -> str:
        return "".join(str(h or "").lower().split())
    ix: Dict[str, int] = {}
    for i, c in enumerate(rows[hi]):
        if c is not None and str(c).strip():
            ix.setdefault(_norm(c), i)
    for need in ("Sales Agent Name", "Signed Date", "Product Category", "Status Code",
                 "Current Line Status", "Cancel Date", "Activation Date", "Order Number",
                 "LineID", "Product Name"):
        if _norm(need) not in ix:
            raise ValueError(f"{Path(sv_path).name}: Order Detail has no '{need}' column")
    body = rows[hi + 1:]

    def g(r, col):
        i = ix.get(_norm(col))
        return r[i] if i is not None and i < len(r) else None

    plan_of: Dict[str, str] = {}
    for r in body:
        if str(g(r, "Product Category") or "").strip() == "Base Plan":
            plan_of.setdefault(str(g(r, "Order Number")), _plan(g(r, "Product Name")))
    out = []
    for r in body:
        if str(g(r, "Product Category") or "").strip() != "Wireless Line":
            continue
        act = _d(g(r, "Activation Date"))
        can = _d(g(r, "Cancel Date"))
        st = dtr_status(str(g(r, "Status Code") or ""), str(g(r, "Current Line Status") or ""), act)
        port = str(g(r, "Port Indicator") or "").upper() == "Y"
        order = str(g(r, "Order Number") or "")
        out.append([
            _rep(g(r, "Sales Agent Name")), st,
            st if st not in ("Posted",) else "Activated",
            _us(_d(g(r, "Signed Date"))), _us(can or act),
            # DTR Active Date: the activation date, or -- for the rate boards --
            # the APPROVAL date (Carlos 2026-11-15: "We shouldn't even be
            # looking at activation rate. We should be looking at approval
            # rate."), so the same NDS rate helpers count approved/sold.
            _us(_d(g(r, "Approval Date")) if date_col == "Approval Date" else act),
            order.split("_")[-1], str(g(r, "LineID") or ""), "",
            "",                                   # Customer Name — never posted
            plan_of.get(order, ""), "Wireless",
            str(g(r, "Item Desc") or "").strip() or str(g(r, "SKU Type") or ""),
            "port" if port else "new",
            str(g(r, "Port Carrier") or "") if port else "",
            "Unit Count",
        ])
    # ONE ROW PER LINE. Credico's Order Detail can list the same line more
    # than once (2026-11-15: Churn Rates by Rep counted 30/366 where the
    # order log's merged lines gave 23/324). Last occurrence wins, the way
    # order_log_tab.merge keeps the newest state for a (order, line) key.
    uniq: Dict[Tuple[str, str], List[str]] = {}
    keep: List[List[str]] = []
    for r in out:
        if not r[7]:                                # no line id: never collapse
            keep.append(r)
            continue
        if (r[6], r[7]) in uniq:                    # sp.SPM Number, spe.TN
            keep[keep.index(uniq[(r[6], r[7])])] = r
        else:
            keep.append(r)
        uniq[(r[6], r[7])] = r
    if len(keep) != len(out):
        print("  nds_rows: %d row(s) -> %d unique line(s)" % (len(out), len(keep)), flush=True)
    blank = sum(1 for r in keep if not r[7])
    if blank:
        print("  nds_rows: %d line(s) with no LineID" % blank, flush=True)
    return list(HEADER), keep


def activation_rate(owner: str, header, rows, target: dt.date, out_dir: Path) -> Tuple[Path, int]:
    """APPROVAL Rate by Rep (nds_orderlog's Activation Rate by Rep board over
    rows whose DTR Active Date is Credico's Approval Date -- nds_rows(...,
    date_col="Approval Date")). Carlos 2026-11-15: approval, not activation,
    is what pays."""
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.office_metrics import nds_orderlog as N
    data = N.activation_by_rep(header, rows, target)
    cols = [w[0] for w in N._ACT_WINDOWS]

    def cell(window, an):
        if not an or not an[1]:
            return {}
        a, n = an
        rate = a / n
        color = next(c for floor, c in N._ACT_BANDS[window] if rate >= floor)
        return {"disc": str(a), "act": str(n), "rate": f"{round(rate * 100, 1)}%", "color": color}

    office = data.pop("__office__", {})
    table = [("Office Total (all reps)", "", True, {c: cell(c, office.get(c)) for c in cols})]
    for rep in sorted(data, key=str.lower):
        table.append((rep, "", False, {c: cell(c, data[rep].get(c)) for c in cols}))
    out = out_dir / f"verizon_approval_rate_{target.isoformat()}.png"
    render_table_png("APPROVAL RATES BY REP",
                     f"{owner} — {target:%B} {target.day}, {target.year} "
                     "(Verizon lines approved/sold, from Credico Sales Verification)",
                     cols, table, out)
    return out, len(table) - 1


def rep_activations(owner, header, rows, target, out_dir) -> List[Path]:
    """The house Rep Activations board (rep_activations build_week_tables +
    render), Posted / Pending / Total / Canceled, FOUR weeks as two pictures:
    the newest two, then the two before (Carlos 2026-11-07: "because pay is
    two weeks behind on this campaign we should have this show 4 weeks").
    Without NDS's shipping split: Credico has no Shipped / Delivered /
    Porting Issue, so those columns would only ever say 0.

    The older picture counts only lines sold by the end of its weeks, so its
    Pending is what was still pending from THEN, not this week's again."""
    import pandas as pd
    from automations.office_metrics import nds_orderlog as N
    from automations.rep_activations.aggregate import build_week_tables, week_bounds
    from automations.rep_activations.render import render
    i = {c: header.index(c) for c in header}

    def frame(upto=None):
        out = []
        for r in rows:
            sold = N._parse_date(r[i["sp.Order Date"]])
            if upto and sold and sold > upto:
                continue
            out.append({"Rep": r[i["Rep"]], "Status": N._house_status(r[i["DTR Status"]]),
                        "Activation Date": r[i["sp.Order Date"]],      # when the rep sold it
                        "Install Date": r[i["Status Date"]]})
        return pd.DataFrame(out)

    older_day = target - dt.timedelta(days=14)
    _ls, _le, _ts, older_end = week_bounds(older_day)
    older = build_week_tables(frame(older_end), older_day)
    older["titles"] = ("3 Weeks Ago", "2 Weeks Ago")
    recent = build_week_tables(frame(), target)
    # ONE PICTURE (Carlos 2026-11-15: "let's keep it on one screenshot ... it
    # doesn't need to be separated into two"): the older pair on top, the
    # newest pair below, drawn with the house renderer's own table pieces.
    return [_four_tables_png(older, recent, out_dir / f"verizon_rep_activations_{target.isoformat()}.png")]


def _four_tables_png(older: dict, recent: dict, out_path: Path) -> Path:
    """2 x 2 grid of the house Rep Activations tables: 3 Weeks Ago | 2 Weeks
    Ago over Last Week | This Week (rep_activations.render's pieces)."""
    from PIL import Image
    from automations.rep_activations import render as R
    fonts = (R._font(16 * R.S, bold=True), R._font(12 * R.S, bold=True),
             R._font(12 * R.S), R._font(12 * R.S, bold=True))
    cols = R._cols(recent.get("pending_cols"))
    alert = frozenset(recent.get("alert_cols") or ())
    rows_of = []
    for summary in (older, recent):
        names = summary.get("titles") or ("Last Week", "This Week")
        rows_of.append((R._build_table(f"{names[0]}: {summary['last']['label']}", summary["last"], fonts, cols, alert),
                        R._build_table(f"{names[1]}: {summary['this']['label']}", summary["this"], fonts, cols, alert)))
    col_w = [max(r[c].width for r in rows_of) for c in range(2)]
    row_h = [max(im.height for im in r) for r in rows_of]
    W = R.PAD * R.S * 2 + col_w[0] + R.GAP * R.S + col_w[1]
    H = R.PAD * R.S * 2 + row_h[0] + R.GAP * R.S + row_h[1]
    canvas = Image.new("RGB", (W, H), R.WHITE)
    y = R.PAD * R.S
    for k, (left, right) in enumerate(rows_of):
        canvas.paste(left, (R.PAD * R.S, y))
        canvas.paste(right, (R.PAD * R.S + col_w[0] + R.GAP * R.S, y))
        y += row_h[k] + R.GAP * R.S
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((W // R.S, H // R.S), Image.LANCZOS).save(out_path)
    return out_path


def pending_orders(owner, header, rows, target, out_dir) -> Tuple[List[Path], int]:
    """Carlos's / NDS's Pending Orders renderer (box_order_log.pending_png),
    one group per rep, oldest first."""
    from automations.box_order_log import pending as bp, pending_png
    from automations.office_metrics import nds_orderlog as N
    i = {c: header.index(c) for c in header}
    cols = ("Order #", "Package", "Device", "Port / New", "Status", "Order Date", "Days Waiting")

    class _Row:
        def __init__(self, r):
            od = N._parse_date(r[i["sp.Order Date"]])
            port = r[i["spe.TN Type"]]
            self.cells = (r[i["sp.SPM Number"]], r[i["Package"]], r[i["spe.Wireless Type"]],
                          f"port ({r[i['spe.Port Carrier']][:16]})" if port == "port" else port,
                          r[i["DTR Status"]], r[i["sp.Order Date"]],
                          str((target - od).days) if od else "")
            self.status = r[i["DTR Status"]].lower()
            self.history = ()
            self.rep, self.sale_date = r[i["Rep"]] or "(no rep)", od
            self.fields = {"Rep Name": self.rep, "Business Name": r[i["sp.SPM Number"]]}

    lines = [_Row(r) for r in rows
             if N._house_status(r[i["DTR Status"]]) not in ("active", "canceled", "disconnected")]
    reps = bp.by_rep(lines)
    parts, cur, cur_n = [], [], 0          # whole reps per image, never split one
    for rep, rr in reps:
        if cur and cur_n + len(rr) > N._PENDING_ROWS_PER_IMAGE:
            parts.append(cur)
            cur, cur_n = [], 0
        cur.append((rep, rr))
        cur_n += len(rr)
    parts.append(cur)
    n = len(lines)
    sub = (f"{n} Verizon line{bp.plural(n)} submitted, not activated yet, as of "
           f"{target:%B} {target.day}, {target.year} — activated and canceled left out.")
    outs = []
    for k, part in enumerate(parts, 1):
        prows = [x for _rep, rr in part for x in rr]
        tag = f" ({k} of {len(parts)})" if len(parts) > 1 else ""
        work = {"today": target, "count": len(prows), "columns": cols,
                "title": f"{owner} — Pending Orders{tag}", "subtitle": sub,
                "color_fn": lambda st, _h: "",
                "sections": [{"key": "p", "title": None, "rows": prows, "reps": part,
                              "empty_note": "Nothing pending — every line is activated or closed."}]}
        suffix = f"_{k}" if len(parts) > 1 else ""
        outs.append(pending_png.render(work, out_dir / f"verizon_pending_orders_{target.isoformat()}{suffix}.png"))
    return outs, n


def status_orders(owner, header, rows, target, out_dir, slug: str) -> Tuple[Path, int]:
    """The house Canceled Orders board (canceled_orders.render) — only lines
    that reached that status in the last nds_orderlog._RECENT_STATUS_DAYS, the
    NDS rule, so a cancel shows up once rather than every day for two weeks."""
    from automations.canceled_orders.render import render
    from automations.office_metrics import nds_orderlog as N
    i = {c: header.index(c) for c in header}
    want = "Disconnected" if slug == "disconnects" else "Canceled"
    cutoff = target - dt.timedelta(days=N._RECENT_STATUS_DAYS)
    hits = [r for r in rows if r[i["DTR Status"]] == want
            and (N._parse_date(r[i["Status Date"]]) or dt.date.min) >= cutoff]
    house = [{"Rep": r[i["Rep"]], "Package": r[i["Package"]], "Device": r[i["spe.Wireless Type"]],
              "Port / New": (f"port ({r[i['spe.Port Carrier']][:16]})" if r[i["spe.TN Type"]] == "port"
                             else r[i["spe.TN Type"]]),
              "Order #": r[i["sp.SPM Number"]], "Order Date": r[i["sp.Order Date"]],
              "Status Date": r[i["Status Date"]]} for r in hits]
    cols = [("Rep", 190), ("Package", 250), ("Device", 150), ("Port / New", 190),
            ("Order #", 110), ("Order Date", 95), ("Status Date", 95)]
    noun = "disconnected" if slug == "disconnects" else "canceled"
    title = "Disconnected Orders" if slug == "disconnects" else "Canceled Orders"
    out = out_dir / f"verizon_{slug}_{target.isoformat()}.png"
    return render(house, out, title=f"{owner} — {title}", cols=cols,
                  empty_note=f"No new Local Office {noun} orders."), len(hits)


def activation_by_week(owner, header, rows, target, out_dir, weeks: int = 6,
                       approved: Optional[set] = None) -> Tuple[Path, int]:
    """APPROVAL Rate by Week-Ending since 2026-11-15 (Carlos: "We should be
    looking at approval rate"): build() hands this rows whose DTR Active Date
    is the Approval Date. The shape is the 11/07 Activation Rate by Week-Ending:
    the lines SOLD in
    each of the last `weeks` Sun-Sat weeks, and how many of those have
    activated since -- "all the sales from X week that have activated, not
    which sales activated on X week". Office total + one row per rep, same
    table and colour bars as Activation Rate by Rep (0-30 day bands). SIX
    weeks, OLDEST on the left and the newest on the far right, like the NDS
    Activation Rate by Week Ending (Carlos 2026-11-15: "let's make sure that
    for that one, we do 6 weeks ... the most recent week is on the far
    right"). Counted "ever activated": a line that activated and later
    disconnected still counts (the Churn board carries the disconnects).

    `approved` = approved_keys(...) over the ACTIVATION rows: approved/sold
    per rep, and under the rep table an office block per week-ending with
    where every line sold that week stands -- approved, pending activation,
    pending approval, canceled, disconnected (Carlos 2026-11-15: "we need
    something that shows how many sales are pending activation, how many
    are pending approval, how many have canceled, how many have
    disconnected"). None = the old board off DTR Active Date, no block."""
    from automations.b2b_metrics.rep_boards import render_sections_png, render_table_png
    from automations.office_metrics import nds_orderlog as N
    from automations.rep_activations.aggregate import week_bounds
    i = {c: header.index(c) for c in header}
    this_sun = week_bounds(target)[2]
    ends = [this_sun - dt.timedelta(days=1 + 7 * k) for k in reversed(range(weeks))]   # oldest first
    cols = [f"WE {e.month}/{e.day}" for e in ends]
    data: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: {c: [0, 0] for c in cols})
    # two kinds of disconnect, looked at separately (Carlos 2026-11-15): after
    # approval (in the churn math) and BEFORE approval (outside it, never paid)
    STANDS = ("Approved", "Pending activation", "Pending approval", "Canceled", "Disconnected",
              "Disconnected before approval")
    stands: Dict[str, Dict[str, int]] = {k: {c: 0 for c in cols} for k in ("Sold",) + STANDS}
    for r in rows:
        sold = N._parse_date(r[i["sp.Order Date"]])
        if not sold:
            continue
        for c, e in zip(cols, ends):
            if e - dt.timedelta(days=6) <= sold <= e:
                if approved is None:
                    act = 1 if r[i["DTR Active Date"]] else 0
                else:
                    act = 1 if (r[i["sp.SPM Number"]], r[i["spe.Name"]]) in approved else 0
                for who in (r[i["Rep"]] or "(no rep)", "__office__"):
                    data[who][c][0] += act
                    data[who][c][1] += 1
                st = r[i["DTR Status"]]
                stands["Sold"][c] += 1
                if st == "Disconnected":
                    stands["Disconnected" if act else "Disconnected before approval"][c] += 1
                elif st == "Canceled":
                    stands["Canceled"][c] += 1
                elif act:
                    stands["Approved"][c] += 1
                elif r[i["DTR Active Date"]]:
                    stands["Pending approval"][c] += 1
                else:
                    stands["Pending activation"][c] += 1

    def cell(an):
        a, n = an
        if not n:
            return {}
        rate = a / n
        color = next(c for floor, c in N._ACT_BANDS["0-30 Day"] if rate >= floor)
        return {"disc": str(a), "act": str(n), "rate": f"{round(rate * 100, 1)}%", "color": color}

    office = data.pop("__office__", {c: [0, 0] for c in cols})
    table = [("Office Total (all reps)", "", True, {c: cell(office[c]) for c in cols})]
    for rep in sorted(data, key=str.lower):
        table.append((rep, "", False, {c: cell(data[rep][c]) for c in cols}))
    out = out_dir / f"verizon_approval_by_week_{target.isoformat()}.png"
    sub = (f"{owner} — lines sold each week that Credico has approved since "
           f"(approved/sold), as of {target:%B} {target.day}")
    if approved is None:
        render_table_png("APPROVAL RATE BY WEEK-ENDING", sub, cols, table, out)
        return out, len(table) - 1
    # the office block: a plain count per cell (no band colour)
    block = [(k, "", k == "Sold", {c: {"rate": str(stands[k][c]), "color": ""} for c in cols})
             for k in ("Sold",) + STANDS]
    render_sections_png("APPROVAL RATE BY WEEK-ENDING", sub, cols, table,
                        [("OFFICE — where every line sold that week stands today", block)], out)
    return out, len(table) - 1


# Churn colour bars. NOT Credico's or Tableau's (neither gives Verizon one):
# lower is better, so the floors run the other way from activation. Megan /
# Carlos to confirm (2026-11-07).
CHURN_BANDS = ((0.05, "Green"), (0.10, "Yellow"), (1.01, "Red"))
CHURN_WINDOWS = (("0-30 Day", 0, 30), ("31-60 Day", 31, 60))


def approved_keys(header, arows) -> set:
    """{(order, line)} of every line carrying Credico's Approval Date, off
    rows built with nds_rows(..., date_col="Approval Date"). The line id sits
    under "spe.Name" in these rows (nds_rows); "spe.TN" is always blank --
    keying on it made every line of an order share one key, so one approved
    line approved the whole order (Churn Rates by Rep 30/366 vs 23/324,
    2026-11-15)."""
    i = {c: header.index(c) for c in header}
    return {(r[i["sp.SPM Number"]], r[i["spe.Name"]]) for r in arows if r[i["DTR Active Date"]]}


def churn(owner, header, rows, target, out_dir, approved: Optional[set] = None,
          lines: Optional[list] = None) -> Tuple[Path, int]:
    """Churn Rates by Rep (Carlos's "What's missing", 2026-11-07): of the
    APPROVED lines activated 0-30 / 31-60 days ago, how many have since
    disconnected (Credico: Status Code CAN with a Disc. line status). Office
    total + one row per rep, the same table Carlos's B2B "CHURN RATES BY REP"
    uses, cells (disconnected/approved) + rate.

    `approved` = approved_keys(...): only those lines count, in the base and
    as disconnects (Carlos 2026-11-15: "It's the disconnects divided by the
    approved activations"; Credico's SOW scores churn on lines that show an
    approval date). None = every activated line (the pre-11/15 board).

    `lines` = order_log_tab.lines(sv): when given, the counts come off THOSE
    merged lines with the churn tab's own rules (churn_tab.churn_units:
    approved, active-or-disconnected, activation inside the window), so the
    office row IS the tab's box (2026-11-15: the row-based count read 30/366
    against the tab's 23/324).

    From the daily Sales Verification, not the weekly Compliance Flags,
    whose churn columns Credico has been leaving blank. That file carries
    about six weeks of sales, so 31-60 only ever holds the lines activated
    31 to ~40 days ago -- the subtitle says so rather than hiding it."""
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.office_metrics import nds_orderlog as N
    i = {c: header.index(c) for c in header}
    cols = [w[0] for w in CHURN_WINDOWS]
    data: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: {c: [0, 0] for c in cols})
    oldest = 0
    if lines is not None:
        from automations.verizon_office import churn_tab as CT
        for l in lines:
            act = CT._d(l.get("Activation Date"))
            if not act or not (CT.is_activated(l) and CT.is_approved(l)):
                continue
            age = (target - act).days
            oldest = max(oldest, age)
            gone = 1 if CT.is_dead(l) else 0
            for name, lo, hi in CHURN_WINDOWS:
                if lo <= age <= hi:
                    for who in (l.get("Rep") or "(no rep)", "__office__"):
                        data[who][name][0] += gone
                        data[who][name][1] += 1
    for r in ([] if lines is not None else rows):
        act = N._parse_date(r[i["DTR Active Date"]])
        if not act:
            continue
        if approved is not None and (r[i["sp.SPM Number"]], r[i["spe.Name"]]) not in approved:
            continue
        age = (target - act).days
        oldest = max(oldest, age)
        gone = 1 if r[i["DTR Status"]] == "Disconnected" else 0
        for name, lo, hi in CHURN_WINDOWS:
            if lo <= age <= hi:
                for who in (r[i["Rep"]] or "(no rep)", "__office__"):
                    data[who][name][0] += gone
                    data[who][name][1] += 1
    if lines is not None and approved is not None:
        # the ROW-based count beside it, until the gap is explained
        rb = {c: [0, 0] for c in cols}
        st_mix: Dict[str, int] = defaultdict(int)
        for r in rows:
            act = N._parse_date(r[i["DTR Active Date"]])
            if act and (r[i["sp.SPM Number"]], r[i["spe.Name"]]) in approved and 0 <= (target - act).days <= 30:
                rb[cols[0]][1] += 1
                rb[cols[0]][0] += 1 if r[i["DTR Status"]] == "Disconnected" else 0
                st_mix[r[i["DTR Status"]] + "/" + r[i["spe.Status"]]] += 1
        print("  churn by rep, row-based 0-30: %d/%d; statuses %s" % (rb[cols[0]][0], rb[cols[0]][1], dict(st_mix)), flush=True)

    def cell(dn):
        d, n = dn
        if not n:
            return {}
        rate = d / n
        color = next(c for ceil, c in CHURN_BANDS if rate <= ceil)
        return {"disc": str(d), "act": str(n), "rate": f"{round(rate * 100, 1)}%", "color": color}

    office = data.pop("__office__", {c: [0, 0] for c in cols})
    print("  churn by rep, office: " + ", ".join("%s %d/%d" % (c, office[c][0], office[c][1]) for c in cols)
          + (" (approved lines only)" if approved is not None else ""), flush=True)
    table = [("Office Total (all reps)", "", True, {c: cell(office[c]) for c in cols})]
    for rep in sorted(data, key=str.lower):
        table.append((rep, "", False, {c: cell(data[rep][c]) for c in cols}))
    partial = (f"; 31-60 covers lines activated 31-{oldest} days ago so far"
               if 31 <= oldest < 60 else "")
    out = out_dir / f"verizon_churn_{target.isoformat()}.png"
    render_table_png("CHURN RATES BY REP",
                     f"{owner} — {target:%B} {target.day}, {target.year} "
                     f"(disconnected/approved lines, by days since activation{partial})",
                     cols, table, out)
    return out, len(table) - 1


# The house order-log writer (uploaded.order_log), Verizon's columns. Date and
# status columns REUSE the house raw names: that is what its date parsing and
# status colours key off (see order_log.column_profile). Install Date rides
# along blank, as on the NDS log: the per-rep tabs are built around it.
_LOG_COLUMNS = ["Rep", "sp.Order Date (copy)", "Activatoin Date (order log)",
                "sp.SPM Number", "Package", "Type", "Ported From", "spe.Status",
                "spe.Install Date"]
_LOG_HEADERS = ["Rep", "Order Date", "Activation Date", "Order #", "Package",
                "Device", "Ported From", "Status", "Install Date"]


def order_log(owner, header, rows, target, out_dir) -> Tuple[Path, int]:
    from automations.uploaded import order_log as house
    i = {c: header.index(c) for c in header}

    def san(v):
        return (v or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

    lines = ["\t".join(_LOG_COLUMNS)]
    for r in rows:
        lines.append("\t".join(san(v) for v in (
            r[i["Rep"]], r[i["sp.Order Date"]], r[i["DTR Active Date"]], r[i["sp.SPM Number"]],
            r[i["Package"]], r[i["spe.Wireless Type"]],
            r[i["spe.Port Carrier"]].split(",")[0].strip() if r[i["spe.TN Type"]] == "port" else "",
            r[i["DTR Status"]], "")))
    tsv = out_dir / f"verizon_order_log_src_{target.isoformat()}.csv"
    tsv.write_text("\n".join(lines), encoding="utf-16")
    # Verizon pays two weeks behind: every pay date one week later than the
    # house Friday-after (Carlos 2026-11-07).
    saved, house.PAY_EXTRA_WEEKS = house.PAY_EXTRA_WEEKS, 1
    try:
        with house.column_profile(_LOG_COLUMNS, _LOG_HEADERS, optional_raw={"Ported From"}):
            return Path(house.csv_to_xlsx(tsv, out_dir, owner=owner)), len(rows)
    finally:
        house.PAY_EXTRA_WEEKS = saved


# (slug, label) in the NDS thread's order (office_metrics.runner._nds_metrics).
BOARDS = [
    ("rep_activations", "🆕 Rep Activations"),
    ("pending_orders", "⏳ Pending Orders"),
    ("activation_rate", "📈 Approval Rate by Rep"),
    ("activation_by_week", "📆 Approval Rate by Week-Ending"),
    ("churn", "📉 Churn Rates by Rep"),
    ("revenue_board", "💰 Revenue Board"),
    ("activation_revenue", "💵 Activation Revenue Overview"),
    ("rep_tiers", "🏅 Rep Tiered Ranking"),
    ("order_log", "📋 Order Log"),
    ("cancels", "🚫 Canceled Orders"),
    ("disconnects", "❎ Disconnected Orders"),
]


def build(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> List[Dict]:
    """[{slug, label, kind: image|file|text, paths, comment}] in thread order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    header, rows = nds_rows(sv_path)
    # the two RATE boards count approved/sold (Carlos 2026-11-15)
    aheader, arows = nds_rows(sv_path, date_col="Approval Date")
    if not rows:
        raise RuntimeError("Order Detail has no wireless lines — not posting blank boards")
    day = f"{target:%b} {target.day}"
    items = []
    for slug, label in BOARDS:
        comment = f"{label} — {day}"
        kind, paths = "image", []
        if slug == "rep_activations":
            paths = rep_activations(owner, header, rows, target, out_dir)
        elif slug == "pending_orders":
            paths, _n = pending_orders(owner, header, rows, target, out_dir)
        elif slug == "activation_rate":
            paths = [activation_rate(owner, aheader, arows, target, out_dir)[0]]
        elif slug == "activation_by_week":
            paths = [activation_by_week(owner, header, rows, target, out_dir,
                                        approved=approved_keys(aheader, arows))[0]]
        elif slug == "churn":
            from automations.verizon_office import order_log_tab as OL
            paths = [churn(owner, header, rows, target, out_dir, approved=approved_keys(aheader, arows),
                           lines=OL.lines(sv_path))[0]]
        elif slug in ("revenue_board", "activation_revenue", "rep_tiers"):
            # Priced on Credico's comp grid (verizon_office.comp); these read
            # the file themselves -- they need fields the NDS rows don't carry.
            # The overview goes as ONE picture (Carlos 2026-11-15).
            from automations.verizon_office import revenue as RV
            fn = RV.activation_revenue_one if slug == "activation_revenue" else getattr(RV, slug)
            got = fn(owner, Path(sv_path).resolve(), target, out_dir.resolve())
            paths = got if isinstance(got, list) else [got]
        elif slug == "order_log":
            kind, paths = "file", [order_log(owner, header, rows, target, out_dir)[0]]
        else:
            png, n = status_orders(owner, header, rows, target, out_dir, slug)
            if n == 0:   # NDS rule: a one-line notice, never a blank image
                noun = "canceled" if slug == "cancels" else "disconnected"
                kind, comment = "text", f"{label} — {day} — No new {noun} orders"
            else:
                paths = [png]
        items.append(dict(slug=slug, label=label, kind=kind, comment=comment, paths=paths))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, required=True)
    ap.add_argument("--owner", default="Nicolas Murrugarra")
    ap.add_argument("--date", help="YYYY-MM-DD (default: the day after the file's data)")
    a = ap.parse_args(argv)
    target = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    items = build(a.owner, a.sv, target, ROOT / "output" / "verizon_office" / "boards")
    for it in items:
        print(f"{it['label']:<28} {it['kind']:<5} {', '.join(str(p) for p in it['paths']) or it['comment']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
