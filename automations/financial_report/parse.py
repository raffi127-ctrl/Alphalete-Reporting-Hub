"""Parse the emailed financial workbooks.

Three layouts are auto-detected per file and merged into one result, so the
user can drop all of them in the same upload folder:

  - **FINANCIAL SUMMARY** — the standard: many offices stacked on one sheet,
    office header in column B '(OWNER-STATE)', metric label in column C, the
    4 week-ending columns D-G.
  - **MONTHLY REPORT** — one office, a sheet per ~6-week block; weeks run
    across columns, metric labels down column A (e.g. German Lopez's file).
  - **CASH FLOW (per-week)** — one office, one sheet per week; each sheet a
    cash-flow + P&L statement (e.g. Coel Reif's file).

Every parser emits the same shape — {normalized owner: office} where each
office is {"office", "owner", "metrics": {METRIC: {week_date: value}}}. The
metric values are date-keyed so the focus-report fill can slot each into the
right week column regardless of how the source file laid its weeks out.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

# Focus-sheet row label  ->  the canonical metric key.
# Aptel / Arcadia Consulting are only written where the tab has that row.
# The 'PNL -Profit %' row is intentionally NOT mapped — no source yet (skip).
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

# Bespoke-format row label (normalized via _lbl) -> canonical metric key.
# Only the metrics Megan confirmed are mapped; anything left out (Indeed,
# Operating %, and for Coel also Aptel/Arcadia/Owners Withdrawal) is simply
# never populated, so the fill doesn't write it.
_GERMAN_METRICS: Dict[str, str] = {
    "current bank balance total": "TOTAL FUNDS AVAILABLE",
    "owner payroll":              "OWNERS PAYROLL",
    "total costs for week":       "TOTAL EXPENSES",
    "ksw/aptel":                  "APTEL",
    "recruiter - arcadia/nlr":    "ARCADIA CONSULTING",
    "owners draw/atm":            "OWNERS WITHDRAWAL",
    "bottom line profit/loss":    "PROFIT/LOSS",
}
_COEL_METRICS: Dict[str, str] = {
    "local balance":  "TOTAL FUNDS AVAILABLE",
    "owner payroll":  "OWNERS PAYROLL",
    "total expense":  "TOTAL EXPENSES",
    "bl profit/loss": "PROFIT/LOSS",
}

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# Coel-style sheet name: a per-week tab like '5.9.26'.
_DATE_SHEET = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*$")


def norm_name(s) -> str:
    """Normalize a person name for matching — lowercase, drop punctuation,
    hyphens to spaces, and a trailing generational suffix (Jr / III / ...)."""
    s = str(s or "").lower().replace("'", "").replace(".", "").replace("-", " ")
    return " ".join(w for w in s.split() if w not in _NAME_SUFFIXES)


def _lbl(s) -> str:
    """Normalize a row label for matching — lowercase, trim, collapse
    whitespace, drop apostrophes (so 'OWNER'S DRAW' == 'owners draw')."""
    s = str(s or "").strip().lower().replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", s)


def _owner_from_office(header: str) -> str:
    """'ABYL ACQUISITION GROUP, INC. (ABEL DRAPER-CT)' -> 'ABEL DRAPER'.
    Takes the trailing parenthetical and strips a 2-letter state code."""
    m = re.search(r"\(([^)]+)\)\s*$", header or "")
    inside = (m.group(1) if m else "").strip()
    return re.sub(r"\s*-\s*[A-Za-z]{2}$", "", inside).strip()


def _detect_format(wb) -> str:
    """'german' | 'coel' | 'summary' — by a signature cell in column A."""
    for name in wb.sheetnames:
        a4 = _lbl(wb[name]["A4"].value)
        if "monthly report" in a4:
            return "german"
        if "statement of cash flows" in a4:
            return "coel"
    return "summary"


def _parse_summary(wb) -> Tuple[List[dict], List[dt.date]]:
    """FINANCIAL SUMMARY layout — offices stacked on the first sheet."""
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
            label = str(c).strip().upper()
            cur["metrics"][label] = {weeks[i]: vals[i]
                                     for i in range(min(len(weeks), len(vals)))
                                     if vals[i] is not None}
    return offices, weeks


def _parse_german(wb) -> Tuple[List[dict], List[dt.date]]:
    """MONTHLY REPORT layout — one office, weeks across columns, metric
    labels down column A. Parses every sheet (one per ~6-week block) and
    merges; the latest sheet wins a boundary week."""
    owner = office = None
    metrics: Dict[str, Dict[dt.date, object]] = {}
    weeks_seen: set = set()
    for name in wb.sheetnames:
        rows = list(wb[name].iter_rows(min_row=1, max_row=wb[name].max_row))
        for r in rows[:4]:
            a = _lbl(r[0].value)
            if a.startswith("company name") and len(r) > 1:
                owner = owner or str(r[1].value or "").strip()
            elif a.startswith("owner") and "name" in a and len(r) > 1:
                office = office or str(r[1].value or "").strip()
        # The DATE row — first row with 4+ datetimes in columns B-G.
        date_cols: Dict[int, dt.date] = {}
        for r in rows:
            cand = {i: r[i].value for i in range(1, 8)
                    if i < len(r) and isinstance(r[i].value, dt.datetime)}
            if len(cand) >= 4:
                date_cols = {i: v.date() for i, v in cand.items()}
                break
        if not date_cols:
            continue
        weeks_seen.update(date_cols.values())
        for r in rows:
            canon = _GERMAN_METRICS.get(_lbl(r[0].value)) if r else None
            if not canon:
                continue
            m = metrics.setdefault(canon, {})
            for ci, d in date_cols.items():
                v = r[ci].value if ci < len(r) else None
                if isinstance(v, (int, float)):
                    m.setdefault(d, v)            # latest sheet wins
    if not owner:
        return [], []
    return ([{"office": office or owner, "owner": owner, "metrics": metrics}],
            sorted(weeks_seen))


def _parse_coel(wb) -> Tuple[List[dict], List[dt.date]]:
    """CASH FLOW layout — one office, one sheet per week. Each metric label
    is found anywhere on the sheet; its value is the first number to the
    right on the same row."""
    owner = office = None
    metrics: Dict[str, Dict[dt.date, object]] = {}
    weeks_seen: set = set()
    for name in wb.sheetnames:
        m = _DATE_SHEET.match(name)
        if not m:
            continue
        mon, day, yr = (int(x) for x in m.groups())
        try:
            week = dt.date(yr + 2000 if yr < 100 else yr, mon, day)
        except ValueError:
            continue
        weeks_seen.add(week)
        ws = wb[name]
        if owner is None:
            owner = str(ws["A2"].value or "").strip()
            office = str(ws["A1"].value or "").strip()
        for r in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 60)):
            for ci, cell in enumerate(r):
                canon = _COEL_METRICS.get(_lbl(cell.value))
                if not canon:
                    continue
                val = next((r[k].value for k in range(ci + 1, len(r))
                            if isinstance(r[k].value, (int, float))), None)
                if val is not None:
                    metrics.setdefault(canon, {}).setdefault(week, val)
    if not owner:
        return [], []
    return ([{"office": office or owner, "owner": owner, "metrics": metrics}],
            sorted(weeks_seen))


def parse_one_file(path) -> Tuple[List[dict], List[dt.date], str]:
    """Parse one workbook — detects its layout and dispatches. Returns
    (offices, weeks, format-name)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    fmt = _detect_format(wb)
    offices, weeks = {"german": _parse_german,
                      "coel": _parse_coel}.get(fmt, _parse_summary)(wb)
    return offices, weeks, fmt


def parse_financial_files(paths, logfn=print) -> Tuple[Dict[str, dict], List[dt.date]]:
    """Parse + merge any number of financial workbooks — any mix of the three
    layouts — into one {normalized owner: office} map. On a duplicate owner
    the later file wins. Returns (by_owner, weeks).

    `weeks` is the reporting window the fill writes into: the FINANCIAL
    SUMMARY week-endings when any summary file is present (Eve's checked
    weeks), otherwise the 4 most recent dates seen. Skips Excel lock files
    (~$...) and any workbook that won't open — a bad upload is logged."""
    by_owner: Dict[str, dict] = {}
    summary_weeks: List[dt.date] = []
    all_weeks: set = set()
    for p in paths:
        if Path(p).name.startswith("~$"):
            continue                       # Excel lock/temp file
        try:
            offices, wk, fmt = parse_one_file(p)
        except Exception as e:
            logfn(f"financial: SKIPPED {Path(p).name} — can't open "
                  f"({type(e).__name__})")
            continue
        logfn(f"financial: {Path(p).name} — {fmt} format, "
              f"{len(offices)} office(s)")
        all_weeks.update(wk)
        if fmt == "summary" and wk:
            summary_weeks = wk
        for o in offices:
            key = norm_name(o["owner"])
            if key:
                by_owner[key] = o
    weeks = summary_weeks or sorted(all_weeks)[-4:]
    return by_owner, weeks
