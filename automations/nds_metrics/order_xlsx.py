"""The NDS Order Log workbook, B2B-style (Carlos 2026-10-29: "build it
that way. also include the customers first and last name in it").

Four kinds of tabs, same shape as the AT&T B2B log:
  1. All Reps        — one row per LINE from the wireless per-line feed,
                       customer first+last on every row
  2. Pending by Rep  — lines still in flight (not Active, not dead)
  3. Paycheck by Week— reps down, DD weeks across, PAID $ straight from
                       the deposit detail (Scoutly RAW, NDS Wireless) —
                       the actual paychecks, not an estimate
  4. one tab per rep — that rep's lines, Rep column dropped
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

GREEN, RED, YELLOW = "C6EFCE", "FFC7CE", "FFF2CC"
DEAD = {"disconnected", "cancelled", "canceled"}
HDR = ["Rep", "Customer", "Order Date", "DSI #", "Wireless Order #",
       "BAN", "Line", "Type", "Device", "Plan", "Line Status",
       "Ship Date", "Delivered", "Port Status"]


def _fill_for(status: str):
    s = (status or "").lower()
    if s == "active":
        return GREEN
    if s in DEAD:
        return RED
    return YELLOW if s else None


def _nice(name: str) -> str:
    from automations.shared.name_case import titlecase_name
    return titlecase_name((name or "").strip())


def _row_of(l: dict):
    return [_nice(l.get("rep", "")), _nice(l.get("customer", "")),
            l.get("order_date", ""), l.get("dsi", ""),
            l.get("wireless_order", ""), l.get("ban", ""),
            l.get("line_no", ""), l.get("line_type", ""),
            l.get("device", ""), l.get("plan", ""),
            l.get("line_status", ""), l.get("ship_date", ""),
            l.get("delivered", ""), l.get("port_status", "")]


def _write_lines(sh, lines, drop_rep=False):
    hdr = HDR[1:] if drop_rep else HDR
    sh.append(hdr)
    for c in sh[1]:
        c.font = Font(bold=True)
    for l in lines:
        row = _row_of(l)
        if drop_rep:
            row = row[1:]
        sh.append(row)
        fill = _fill_for(l.get("line_status", ""))
        if fill:
            for cell in sh[sh.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
    for ci, label in enumerate(hdr, start=1):
        w = max([len(str(label))] +
                [len(str(sh.cell(row=r, column=ci).value or ""))
                 for r in range(2, sh.max_row + 1)])
        sh.column_dimensions[get_column_letter(ci)].width = min(w + 2, 42)
    sh.freeze_panes = "A2"


def _safe_title(name, used):
    t = re.sub(r"[\\/?*\[\]:]", " ", str(name)).strip()[:28] or "Sheet"
    base, n = t, 2
    while t.lower() in used:
        t = f"{base[:25]} {n}"
        n += 1
    used.add(t.lower())
    return t


def _paycheck_tab(wb, used, log):
    """Reps x DD-week $ matrix from the Scoutly RAW tab — the real
    paychecks. Fails soft: no sheet access leaves the tab out, never
    sinks the workbook."""
    try:
        from automations.recruiting_report.fill import open_by_key
        sh = open_by_key("1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY")
        raw = next(w for w in sh.worksheets()
                   if w.title.strip().lower() == "raw")
        vals = raw.get_all_values()
    except Exception as e:  # noqa: BLE001
        log(f"[ndsx] paycheck tab skipped ({type(e).__name__})")
        return
    hix = {h: i for i, h in enumerate(vals[0])}

    def money(v):
        try:
            return float(str(v).replace("$", "").replace(",", "") or 0)
        except ValueError:
            return 0.0

    paid = collections.defaultdict(float)
    weeks, reps = [], set()
    for r in vals[1:]:
        if not (r and r[0].strip()
                and r[hix["Campaign"]].strip() == "NDS Wireless"):
            continue
        wk, rep = r[0].strip(), _nice(r[hix["Rep Name"]])
        if wk not in weeks:
            weeks.append(wk)
        reps.add(rep)
        paid[(rep, wk)] += money(r[hix["Total $ to ICD"]])
    if not reps:
        return
    psh = wb.create_sheet(_safe_title("Paycheck by Week", used))
    psh.append(["Paid $ per rep per DD week (straight from the deposit "
                "detail — NDS Wireless, all buckets)"])
    psh.cell(row=1, column=1).font = Font(bold=True)
    psh.append(["Rep"] + [f"WE {w}" for w in weeks])
    for c in psh[2]:
        c.font = Font(bold=True)
    for rep in sorted(reps, key=lambda x: -sum(
            paid.get((x, w), 0) for w in weeks)):
        psh.append([rep] + [round(paid.get((rep, w), 0)) or ""
                            for w in weeks])
    psh.append(["TOTAL"] + [round(sum(paid.get((r, w), 0) for r in reps))
                            for w in weeks])
    for c in psh[psh.max_row]:
        c.font = Font(bold=True)
    psh.freeze_panes = "B3"


def build(orders, lines, today: dt.date, out_dir: Path, log=print) -> Path:
    out = out_dir / f"NDS Order Log {today.strftime('%m-%d-%Y')}.xlsx"
    wb = Workbook()
    used: set = set()
    lines = sorted(lines, key=lambda l: (_nice(l.get("rep", "")),
                                         l.get("order_date", ""),
                                         l.get("dsi", "")))
    # 1. All Reps
    sh = wb.active
    sh.title = _safe_title("All Reps", used)
    _write_lines(sh, lines)
    # 2. Pending by Rep
    pend = [l for l in lines
            if (l.get("line_status") or "").lower() not in
            ({"active"} | DEAD)]
    _write_lines(wb.create_sheet(_safe_title("Pending by Rep", used)), pend)
    # 3. Paycheck by Week (from the DD)
    _paycheck_tab(wb, used, log)
    # 4. one tab per rep
    by_rep = collections.defaultdict(list)
    for l in lines:
        r = _nice(l.get("rep", ""))
        if r:
            by_rep[r].append(l)
    for rep in sorted(by_rep):
        _write_lines(wb.create_sheet(_safe_title(rep, used)),
                     by_rep[rep], drop_rep=True)
    wb.save(out)
    log(f"[ndsx] order log workbook: {len(lines)} line(s), "
        f"{len(by_rep)} rep tab(s), pending {len(pend)}")
    return out
