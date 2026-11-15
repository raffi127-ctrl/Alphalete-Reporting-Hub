"""Nico's Verizon customers' LINE NUMBERS, off Credico ARC's weekly Commissions
workbooks -> the 'VZ Credico Lines' tab on the control sheet. RUNS ON LUCY 1
(where credico_fetch lands the files).

Carlos 2026-11-15: "Keep looking through all the Verizon files and see if
there's somewhere where we can get the customer's phone number ... Go ahead
and add in the customers you see on there."

Credico's daily Sales Verification masks the line to its last four
("*1309-LINE"). The Commissions workbook (`<Saturday>~High Value~
Commissions.xlsx`, Sales Management -> Fee Reports, credico.report.fetch_week)
does not: its DetailAndStatus sheet ("Combined CommissionDetail and
StatusChanges") carries `ExternalLineID` = "9722519486-LINE" on every paid
or status-changed line, beside CustomerName (first + last initial),
AccountNum, the order (ExternalID "Q971801_<order>"), AgentName, SignedDate,
ApprDate, CanDate, ClientStatus, ARCStatus, StatusReason, ProductCode, the
SaleWeek and -- from the CommissionDetail rows -- what was paid and when.
Probed 2026-11-15: 37 columns; 336 distinct numbers across the three files
then on Lucy 1, 47% of the Order Log's lines (the rest: two October files not
fetched yet, and the last two sale weeks Credico has not paid -- it runs two
weeks behind).

ONE ROW PER LINE, merged across every file by (order, number): the newest
file's status wins, Paid Week / Paid $ come from the first ISOFee row seen.
Full rewrite of the tab each run (the files on disk are the durable truth).
Nothing posts to Slack. rc_contact_sync.verizon reads the tab on Lucy 2.

    python -m automations.verizon_office.credico_lines              # dry run: counts
    python -m automations.verizon_office.credico_lines --write      # the tab
    lucy rerun verizon_credico_lines -- --write

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
CREDICO_OUT = ROOT / "output" / "credico"
CACHE = ROOT / "output" / "verizon_office" / "credico_lines.json"
CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "VZ Credico Lines"
NEEDLE = "High-Value"
SHEET = "DetailAndStatus"

HEADERS = ("Customer", "Phone", "Account", "Order #", "Line", "Rep", "Signed Date", "Sale Week",
           "Approval Date", "Cancel Date", "Client Status", "ARC Status", "Status Reason",
           "Product", "Paid Week", "Paid $", "Kicker $", "Files", "Last Updated")
_COL = {h: i for i, h in enumerate(HEADERS)}


def _norm_h(s) -> str:
    return "".join(str(s or "").lower().split())


def _find(header, *cands) -> Optional[int]:
    norm = [_norm_h(h) for h in header]
    for c in cands:
        if _norm_h(c) in norm:
            return norm.index(_norm_h(c))
    return None


def _d(v) -> str:
    if isinstance(v, dt.datetime):
        return v.strftime("%m/%d/%Y")
    if isinstance(v, dt.date):
        return v.strftime("%m/%d/%Y")
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return s


def _rep(name) -> str:
    s = " ".join(str(name or "").split())
    if "," in s:                       # "Murrugarra, Nicolas" -> "Nicolas Murrugarra"
        last, first = s.split(",", 1)
        return (first.strip() + " " + last.strip()).strip()
    return s


def _phone(ext_line_id) -> str:
    m = re.match(r"\s*(\d{10})-", str(ext_line_id or ""))
    return m.group(1) if m else ""


def _order(ext_id) -> str:
    return str(ext_id or "").split("_")[-1].strip()


def files(folder: Path = CREDICO_OUT) -> List[Path]:
    """Oldest Saturday first, so a newer file's status wins in the merge."""
    return sorted(p for p in Path(folder).glob("*.xlsx") if NEEDLE.lower() in p.name.lower())


def read_file(path: Path) -> List[dict]:
    """Every DetailAndStatus row with a 10-digit line number, as a dict."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if SHEET not in wb.sheetnames:
        raise RuntimeError(f"{path.name}: no '{SHEET}' sheet (has {', '.join(wb.sheetnames)})")
    ws = wb[SHEET]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next((i for i, r in enumerate(rows) if r and "OfficeID" in [str(c) for c in r]), None)
    if hi is None:
        raise RuntimeError(f"{path.name}: {SHEET} has no OfficeID header row")
    header = [str(c) if c is not None else "" for c in rows[hi]]
    ix = {k: _find(header, *c) for k, c in {
        "line": ("ExternalLineID",), "ext": ("ExternalID",), "cust": ("CustomerName",),
        "acct": ("AccountNum",), "rep": ("AgentName",), "signed": ("SignedDate",),
        "sale_week": ("SaleWeek",), "appr": ("ApprDate",), "can": ("CanDate",),
        "cstatus": ("ClientStatus",), "astatus": ("ARCStatus",), "reason": ("StatusReason",),
        "product": ("ProductCode",), "item": ("CommissionItem",), "cweek": ("CommissionWeek",),
        "amt": ("TransAmt",), "group": ("CommissionGroup",)}.items()}
    for need in ("line", "ext", "cust"):
        if ix[need] is None:
            raise RuntimeError(f"{path.name}: {SHEET} has no {need} column")

    def g(r, k):
        i = ix.get(k)
        return r[i] if i is not None and i < len(r) else None

    out = []
    for r in rows[hi + 1:]:
        phone = _phone(g(r, "line"))
        if not phone:
            continue
        out.append({
            "phone": phone, "order": _order(g(r, "ext")), "line": phone[-4:],
            "customer": " ".join(str(g(r, "cust") or "").split()).title(),
            "account": str(g(r, "acct") or "").strip(), "rep": _rep(g(r, "rep")),
            "signed": _d(g(r, "signed")), "sale_week": str(g(r, "sale_week") or "").strip(),
            "appr": _d(g(r, "appr")), "cancel": _d(g(r, "can")),
            "cstatus": str(g(r, "cstatus") or "").strip(), "astatus": str(g(r, "astatus") or "").strip(),
            "reason": str(g(r, "reason") or "").strip(), "product": str(g(r, "product") or "").strip(),
            "item": str(g(r, "item") or "").strip(), "cweek": str(g(r, "cweek") or "").strip(),
            "group": str(g(r, "group") or "").strip(),
            "amt": float(g(r, "amt") or 0) if str(g(r, "amt") or "").replace(".", "", 1).replace("-", "", 1).isdigit() else 0.0,
            "file": path.name,
        })
    return out


def merge(rows_by_file: List[Tuple[str, List[dict]]], stamp: str) -> List[List[str]]:
    """One tab row per (order, phone). Files oldest first: status fields from
    the newest row, Paid Week from the first ISOFee row, Paid $ = all ISOFee
    rows summed, Kicker $ = all Bonuses rows summed."""
    lines: "collections.OrderedDict[tuple, dict]" = collections.OrderedDict()
    for fname, rows in rows_by_file:
        for r in rows:
            k = (r["order"], r["phone"])
            cur = lines.setdefault(k, {"paid": 0.0, "kick": 0.0, "paid_week": "", "files": []})
            for f in ("customer", "account", "rep", "signed", "sale_week", "appr", "cancel",
                      "cstatus", "astatus", "reason", "product", "phone", "order", "line"):
                if r.get(f):
                    cur[f] = r[f]
            if r["item"] == "ISOFee":
                cur["paid"] += r["amt"]
                cur["paid_week"] = cur["paid_week"] or r["cweek"]
            elif r["group"] == "Bonuses" or "Kicker" in r["item"]:
                cur["kick"] += r["amt"]
            if fname not in cur["files"]:
                cur["files"].append(fname)
    out = []
    for cur in lines.values():
        out.append([cur.get("customer", ""), cur["phone"], cur.get("account", ""), cur["order"], cur["line"],
                    cur.get("rep", ""), cur.get("signed", ""), cur.get("sale_week", ""), cur.get("appr", ""),
                    cur.get("cancel", ""), cur.get("cstatus", ""), cur.get("astatus", ""), cur.get("reason", ""),
                    cur.get("product", ""), cur["paid_week"], "%.0f" % cur["paid"] if cur["paid"] else "",
                    "%.0f" % cur["kick"] if cur["kick"] else "",
                    ", ".join(f[:10] for f in cur["files"]), stamp])
    out.sort(key=lambda r: (r[_COL["Signed Date"]][-4:] + r[_COL["Signed Date"]][:5], r[_COL["Customer"]]))
    return out


def build(folder: Path = CREDICO_OUT, today: Optional[dt.date] = None, log=print) -> List[List[str]]:
    fs = files(folder)
    if not fs:
        raise RuntimeError(f"no *{NEEDLE}* Commissions workbook in {folder} -- run credico_fetch first")
    by_file = []
    for p in fs:
        rows = read_file(p)
        log("  %s: %d line row(s)" % (p.name, len(rows)))
        by_file.append((p.name, rows))
    stamp = (today or dt.date.today()).strftime("%m/%d/%Y")
    return merge(by_file, stamp)


def push(rows: List[List[str]], *, log=print) -> int:
    from automations.recruiting_report.fill import _retry, open_by_key
    sh = open_by_key(CONTROL_SHEET)
    import gspread
    try:
        ws = sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = _retry(lambda: sh.add_worksheet(title=TAB, rows=max(500, len(rows) + 50), cols=len(HEADERS)))
    body = [list(HEADERS)] + [["'" + c if i in (_COL["Phone"], _COL["Account"], _COL["Order #"], _COL["Line"]) and c.isdigit() else c
                               for i, c in enumerate(r)] for r in rows]
    _retry(lambda: ws.resize(rows=max(500, len(body) + 50), cols=len(HEADERS)))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(body, "A1", value_input_option="USER_ENTERED"))
    _retry(lambda: ws.freeze(rows=1))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps([dict(zip(HEADERS, r)) for r in rows], indent=1))
    log("[verizon] %s: %d line(s), %d customer order(s) -> control sheet + %s"
        % (TAB, len(rows), len({r[_COL['Order #']] for r in rows}), CACHE.name))
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, default=CREDICO_OUT)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = build(a.folder)
    except RuntimeError as e:
        print("✗ %s" % e)
        return 1
    print("%d line(s) with a number, %d customer order(s), %d distinct number(s)"
          % (len(rows), len({r[_COL['Order #']] for r in rows}), len({r[_COL['Phone']] for r in rows})))
    if not a.write:
        print("DRY RUN -- nothing written")
        return 0
    push(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
