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


def nds_rows(sv_path: Path) -> Tuple[List[str], List[List[str]]]:
    """(HEADER, rows) — Order Detail's wireless lines in NDS ORDER LOG shape."""
    ws = openpyxl.load_workbook(sv_path, data_only=True, read_only=True)["Order Detail"]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next(i for i, r in enumerate(rows) if r and "Sales Agent Name" in r)
    ix = {str(c): i for i, c in enumerate(rows[hi]) if c}
    for need in ("Sales Agent Name", "Signed Date", "Product Category", "Status Code",
                 "Current Line Status", "Cancel Date", "Activation Date", "Order Number",
                 "LineID", "Product Name"):
        if need not in ix:
            raise ValueError(f"{Path(sv_path).name}: Order Detail has no '{need}' column")
    body = rows[hi + 1:]

    def g(r, col):
        i = ix.get(col)
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
            _us(_d(g(r, "Signed Date"))), _us(can or act), _us(act),
            order.split("_")[-1], str(g(r, "LineID") or ""), "",
            "",                                   # Customer Name — never posted
            plan_of.get(order, ""), "Wireless",
            str(g(r, "Item Desc") or "").strip() or str(g(r, "SKU Type") or ""),
            "port" if port else "new",
            str(g(r, "Port Carrier") or "") if port else "",
            "Unit Count",
        ])
    return list(HEADER), out


def activation_rate(owner: str, header, rows, target: dt.date, out_dir: Path) -> Tuple[Path, int]:
    """nds_orderlog's Activation Rate by Rep board, totals from the same file
    (there is no Tableau activation view for Verizon)."""
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
    out = out_dir / f"verizon_activation_rate_{target.isoformat()}.png"
    render_table_png("ACTIVATION RATES BY REP",
                     f"{owner} — {target:%B} {target.day}, {target.year} "
                     "(Verizon lines activated/sold, from Credico Sales Verification)",
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
    return [render(build_week_tables(frame(), target),
                   out_dir / f"verizon_rep_activations_{target.isoformat()}.png"),
            render(older, out_dir / f"verizon_rep_activations_{target.isoformat()}_older.png")]


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


def activation_by_week(owner, header, rows, target, out_dir, weeks: int = 4) -> Tuple[Path, int]:
    """Activation Rate by Week-Ending (Carlos 2026-11-07): the lines SOLD in
    each of the last `weeks` Sun-Sat weeks, and how many of those have
    activated since -- "all the sales from X week that have activated, not
    which sales activated on X week". Office total + one row per rep, same
    table and colour bars as Activation Rate by Rep (0-30 day bands: the
    newest four weeks are all inside 30 days)."""
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.office_metrics import nds_orderlog as N
    from automations.rep_activations.aggregate import week_bounds
    i = {c: header.index(c) for c in header}
    this_sun = week_bounds(target)[2]
    ends = [this_sun - dt.timedelta(days=1 + 7 * k) for k in range(weeks)]   # newest first
    cols = [f"WE {e.month}/{e.day}" for e in ends]
    data: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: {c: [0, 0] for c in cols})
    for r in rows:
        sold = N._parse_date(r[i["sp.Order Date"]])
        if not sold:
            continue
        for c, e in zip(cols, ends):
            if e - dt.timedelta(days=6) <= sold <= e:
                act = 1 if r[i["DTR Active Date"]] else 0
                for who in (r[i["Rep"]] or "(no rep)", "__office__"):
                    data[who][c][0] += act
                    data[who][c][1] += 1

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
    out = out_dir / f"verizon_activation_by_week_{target.isoformat()}.png"
    render_table_png("ACTIVATION RATE BY WEEK-ENDING",
                     f"{owner} — lines sold each week that have activated since "
                     f"(activated/sold), as of {target:%B} {target.day}",
                     cols, table, out)
    return out, len(table) - 1


# Churn colour bars. NOT Credico's or Tableau's (neither gives Verizon one):
# lower is better, so the floors run the other way from activation. Megan /
# Carlos to confirm (2026-11-07).
CHURN_BANDS = ((0.05, "Green"), (0.10, "Yellow"), (1.01, "Red"))
CHURN_WINDOWS = (("0-30 Day", 0, 30), ("31-60 Day", 31, 60))


def churn(owner, header, rows, target, out_dir) -> Tuple[Path, int]:
    """Churn Rates by Rep (Carlos's "What's missing", 2026-11-07): of the lines
    ACTIVATED 0-30 / 31-60 days ago, how many have since disconnected
    (Credico: Status Code CAN with a Disc. line status). Office total + one
    row per rep, the same table Carlos's B2B "CHURN RATES BY REP" uses, cells
    (disconnected/activated) + rate.

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
    for r in rows:
        act = N._parse_date(r[i["DTR Active Date"]])
        if not act:
            continue
        age = (target - act).days
        oldest = max(oldest, age)
        gone = 1 if r[i["DTR Status"]] == "Disconnected" else 0
        for name, lo, hi in CHURN_WINDOWS:
            if lo <= age <= hi:
                for who in (r[i["Rep"]] or "(no rep)", "__office__"):
                    data[who][name][0] += gone
                    data[who][name][1] += 1

    def cell(dn):
        d, n = dn
        if not n:
            return {}
        rate = d / n
        color = next(c for ceil, c in CHURN_BANDS if rate <= ceil)
        return {"disc": str(d), "act": str(n), "rate": f"{round(rate * 100, 1)}%", "color": color}

    office = data.pop("__office__", {c: [0, 0] for c in cols})
    table = [("Office Total (all reps)", "", True, {c: cell(office[c]) for c in cols})]
    for rep in sorted(data, key=str.lower):
        table.append((rep, "", False, {c: cell(data[rep][c]) for c in cols}))
    partial = (f"; 31-60 covers lines activated 31-{oldest} days ago so far"
               if 31 <= oldest < 60 else "")
    out = out_dir / f"verizon_churn_{target.isoformat()}.png"
    render_table_png("CHURN RATES BY REP",
                     f"{owner} — {target:%B} {target.day}, {target.year} "
                     f"(disconnected/activated, by days since activation{partial})",
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
    ("activation_rate", "📈 Activation Rate by Rep"),
    ("activation_by_week", "📆 Activation Rate by Week-Ending"),
    ("churn", "📉 Churn Rates by Rep"),
    ("order_log", "📋 Order Log"),
    ("cancels", "🚫 Canceled Orders"),
    ("disconnects", "❎ Disconnected Orders"),
]


def build(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> List[Dict]:
    """[{slug, label, kind: image|file|text, paths, comment}] in thread order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    header, rows = nds_rows(sv_path)
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
            paths = [activation_rate(owner, header, rows, target, out_dir)[0]]
        elif slug == "activation_by_week":
            paths = [activation_by_week(owner, header, rows, target, out_dir)[0]]
        elif slug == "churn":
            paths = [churn(owner, header, rows, target, out_dir)[0]]
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
