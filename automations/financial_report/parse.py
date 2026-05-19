"""Parse the emailed FINANCIAL SUMMARY workbooks.

Each file is one 'Report' sheet — a vertical stack of office blocks:
  - office header in column B:  'COMPANY, INC. (OWNER NAME-STATE)'
  - metric label in column C;  the 4 week-ending columns are D-G
  - the 4 week-ending dates sit on a row above the first office block
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

# Focus-sheet row label  ->  the metric's label in the FINANCIAL SUMMARY file.
# Aptel / Arcadia Consulting are only written where the tab has that row.
FINANCIAL_METRICS: Dict[str, str] = {
    "Total Funds Available": "TOTAL FUNDS AVAILABLE",
    "Owners Payroll":        "OWNERS PAYROLL",
    "Total Expenses":        "TOTAL EXPENSES",
    "Indeed":                "INDEED",
    "Aptel":                 "APTEL",
    "Arcadia Consulting":    "ARCADIA CONSULTING",
    "Owners Withdrawal":     "OWNERS WITHDRAWAL",
    "Profit/Loss":           "PROFIT/LOSS",
    "Operating %":           "OPERATING PERCENTAGE %",
}


def norm_name(s) -> str:
    """Normalize a person name for matching — lowercase, drop punctuation."""
    s = str(s or "").lower().replace("'", "").replace(".", "")
    return " ".join(s.split())


def _owner_from_office(header: str) -> str:
    """'ABYL ACQUISITION GROUP, INC. (ABEL DRAPER-CT)' -> 'ABEL DRAPER'.
    Takes the trailing parenthetical and strips a 2-letter state code."""
    m = re.search(r"\(([^)]+)\)\s*$", header or "")
    inside = (m.group(1) if m else "").strip()
    return re.sub(r"\s*-\s*[A-Za-z]{2}$", "", inside).strip()


def parse_financial_file(path) -> Tuple[List[dict], List[dt.date]]:
    """Parse one FINANCIAL SUMMARY workbook.

    Returns (offices, weeks):
      offices — [{"office": str, "owner": str, "metrics": {LABEL: [v1..v4]}}]
      weeks   — the 4 week-ending dates from columns D-G
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    weeks: List[dt.date] = []
    offices: List[dict] = []
    cur: Optional[dict] = None
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        b = row[1].value if len(row) > 1 else None
        c = row[2].value if len(row) > 2 else None
        vals = [(row[i].value if len(row) > i else None) for i in range(3, 7)]
        if not weeks and all(isinstance(v, dt.datetime) for v in vals):
            weeks = [v.date() for v in vals]
            continue
        if b and "(" in str(b) and ")" in str(b):
            cur = {"office": str(b).strip(),
                   "owner": _owner_from_office(str(b)),
                   "metrics": {}}
            offices.append(cur)
        elif c and cur is not None:
            cur["metrics"][str(c).strip().upper()] = vals
    return offices, weeks


def parse_financial_files(paths, logfn=print) -> Tuple[Dict[str, dict], List[dt.date]]:
    """Parse + merge any number of FINANCIAL SUMMARY workbooks into one
    {normalized owner: office dict} map. On a duplicate owner (an office that
    appears in two files) the later file wins. Returns (by_owner, weeks).

    Skips Excel lock files (~$...) and any workbook that won't open — a bad
    upload is logged, not fatal."""
    by_owner: Dict[str, dict] = {}
    weeks: List[dt.date] = []
    for p in paths:
        if Path(p).name.startswith("~$"):
            continue                       # Excel lock/temp file
        try:
            offices, wk = parse_financial_file(p)
        except Exception as e:
            logfn(f"financial: SKIPPED {Path(p).name} — can't open "
                  f"({type(e).__name__})")
            continue
        if wk:
            weeks = wk
        for o in offices:
            key = norm_name(o["owner"])
            if key:
                by_owner[key] = o
    return by_owner, weeks
