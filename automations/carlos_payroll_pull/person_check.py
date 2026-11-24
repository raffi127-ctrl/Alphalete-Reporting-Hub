"""What Apex shows for one person over the newest completed pay periods
(Carlos 2026-11-24: "check apex. are you sure this is [a rep's] 2nd check? and
shes only gotten one bonus?").

READ-ONLY in Apex: the same path the Thursday pull takes (Payroll Entry -> pay
period dropdown -> Export), nothing typed, saved or submitted. The exported
CSVs are deleted. The person's lines go to the 'Apex Person Check' tab of
Carlos's own Business & Personal P&L; the log only says how many were found, so
pay stays out of the logs and the control sheet. Lucy 2 only: Carlos's Apex
session lives there.

  python -m automations.carlos_payroll_pull.person_check --who jane --periods 4
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import tempfile
from pathlib import Path

TAB = "Apex Person Check"
SECTIONS = ("Owner", "Office Admins", "Sales Reps", "Contractors")
HEADER = ["Period start", "Period end", "Section", "First Name", "Last Name", "Gross Pay",
          "Net Pay Addition", "Net Pay Deduction", "Comments", "Every column on the line"]


def person_rows(text: str, who: str) -> list:
    """Export text -> the rows whose name holds every word of `who`."""
    words = who.lower().split()
    sec = hdr = None
    per = ("", "")
    out = []
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("Pay Period,"):
            a, b = t.split(",", 1)[1].split(" - ")
            per = (a.strip(), b.strip())
        elif t in SECTIONS:
            sec, hdr = t, None
        elif t.startswith("Total,") or t.startswith("Company Total"):
            sec = hdr = None
        elif sec and hdr is None and t.startswith("First Name"):
            hdr = next(csv.reader([t]))
        elif sec and hdr and t:
            d = dict(zip(hdr, next(csv.reader([t]))))
            name = f"{d.get('First Name') or ''} {d.get('Last Name') or ''}".lower()
            if all(w in name for w in words):
                out.append([*per, sec, d.get("First Name", ""), d.get("Last Name", ""), d.get("Gross Pay", ""),
                            d.get("Net Pay Addition", ""), d.get("Net Pay Deduction", ""), d.get("Comments", ""),
                            "; ".join(f"{k}={v}" for k, v in d.items() if v)])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", required=True, help="word(s) of the person's name")
    ap.add_argument("--periods", type=int, default=4, help="newest N completed periods")
    args = ap.parse_args(argv)
    from automations.carlos_payroll_pull import run as AP
    from automations.recruiting_report import fill as _fill
    from patchright.sync_api import sync_playwright

    AP.ensure_chrome()
    found, looked = [], []
    with tempfile.TemporaryDirectory(prefix="apex-person-") as tmp, sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{AP.CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[-1] if ctx.pages else ctx.new_page()
        AP.goto_payroll_entry(page)
        today = dt.date.today()
        done = [x for x in AP.list_periods(page) if x[2] < today][: args.periods]
        old, AP.OUT_DIR = AP.OUT_DIR, Path(tmp)
        try:
            for idx, _start, end in done:
                path = AP.export_period(page, idx, end)
                rows = person_rows(path.read_text(encoding="utf-8-sig", errors="replace"), args.who)
                looked.append([end.isoformat(), len(rows)])
                found += rows or [["", end.strftime("%m/%d/%Y"), "not on this period's payroll"] + [""] * 7]
                path.unlink()
        finally:
            AP.OUT_DIR = old
    book = _fill.open_by_key(AP.PNL_SHEET_ID)
    try:
        ws = book.worksheet(TAB)
        ws.clear()
    except Exception:  # noqa: BLE001 -- first run makes the tab
        ws = book.add_worksheet(TAB, rows=60, cols=len(HEADER))
    stamp = dt.datetime.now().strftime("%-m/%-d/%Y %-I:%M %p")
    ws.update(range_name="A1", values=[[f"Apex lines for '{args.who}', read {stamp}"], HEADER] + found,
              value_input_option="RAW")
    print(f"person check: periods looked at (end, lines found) {looked}; written to '{TAB}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
