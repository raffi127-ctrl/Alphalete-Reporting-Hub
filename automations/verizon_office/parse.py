"""Read Credico's two Verizon Wireless office spreadsheets — first office: Nico
Murrugarra (High Value Acquisitions, Inc., Grand Prairie TX; Carlos org).

Both arrive in the office's Credico Outlook mailbox from vzreports@credicousa.com:

  * 'Sales Verification - Verizon Wireless - <Office> - YYYYMMDD.xlsx' — daily
    ~10:45am CT, sales through YESTERDAY. Sheets used:
      Overview       one row per sales week (10 weeks): HC, valid lines and how
                     they progressed (Sub./Canc./Actv./Disc./Appr. + %s).
      Sales by Week  per REP per day, one block per week, each block opened by a
                     'Week Ending <Month D, YYYY>' row followed by its header row.
      References     Credico's own definition of every Overview column.
    'Order Detail' has customer names: never read into anything that posts.
  * 'Compliance Flags - Verizon Wireless - <Office> - YYYYMMDD.xlsx' — weekly
    (Wed), the week before. One row per rep: flag count + 0-30/30/60/90-day
    churn vs the campaign.

Every column is found by its header label, never by position (templates change).
Credico weeks run Sun-Sat.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _rows(ws) -> List[tuple]:
    return [r for r in ws.iter_rows(values_only=True)]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _header_index(row) -> Dict[str, int]:
    return {_clean(c): i for i, c in enumerate(row) if _clean(c)}


def file_date(path: Path) -> Optional[dt.date]:
    """The YYYYMMDD stamp at the end of Credico's file name."""
    m = re.search(r"(\d{8})\.xlsx$", path.name)
    return dt.datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


@dataclass
class RepWeek:
    name: str
    sso: str
    days: Dict[str, int]
    lines: int
    sales: int
    vals: Dict[str, float] = field(default_factory=dict)   # every other column, by label


@dataclass
class Week:
    end: dt.date                       # Saturday
    reps: List[RepWeek]

    @property
    def lines(self) -> int:
        return sum(r.lines for r in self.reps)


@dataclass
class SalesVerification:
    path: Path
    through: Optional[dt.date]         # last day with data (file date - 1)
    office: str
    weeks: List[Week]                  # newest first
    overview: List[Dict[str, object]]  # newest first, keyed by Overview header label
    references: Dict[str, str]         # column -> Credico's description


def read_sales_verification(path: Path) -> SalesVerification:
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    names = {ws.title: ws for ws in wb.worksheets}
    for need in ("Overview", "Sales by Week", "References"):
        if need not in names:
            raise ValueError(f"{path.name}: no '{need}' sheet — Credico changed the file")

    # Sales by Week: blocks opened by 'Week Ending …'
    weeks: List[Week] = []
    rows = _rows(names["Sales by Week"])
    office = ""
    i = 0
    while i < len(rows):
        first = _clean(rows[i][0]) if rows[i] else ""
        m = re.match(r"Week Ending (\w+ \d{1,2}, \d{4})", first)
        if not m:
            i += 1
            continue
        end = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
        hdr = _header_index(rows[i + 1])
        for need in ("Sales Agent Name", "SSO ID", "Valid Lines", "Valid Sales", *DAYS):
            if need not in hdr:
                raise ValueError(f"{path.name}: 'Sales by Week' block {end} has no '{need}' column")
        reps = []
        j = i + 2
        while j < len(rows) and rows[j] and _clean(rows[j][hdr["Sales Agent Name"]]):
            r = rows[j]
            office = office or _clean(r[hdr["Office Name"]]) if "Office Name" in hdr else office
            reps.append(RepWeek(
                name=_clean(r[hdr["Sales Agent Name"]]),
                sso=_clean(r[hdr["SSO ID"]]),
                days={d: int(_num(r[hdr[d]])) for d in DAYS},
                lines=int(_num(r[hdr["Valid Lines"]])),
                sales=int(_num(r[hdr["Valid Sales"]])),
                vals={k: _num(r[x]) for k, x in hdr.items()
                      if k not in ("Owner Name", "Office Name", "Sales Agent Name", "SSO ID", *DAYS)},
            ))
            j += 1
        weeks.append(Week(end=end, reps=reps))
        i = j
    if not weeks:
        raise ValueError(f"{path.name}: no 'Week Ending' blocks in 'Sales by Week'")
    weeks.sort(key=lambda w: w.end, reverse=True)

    # Overview: header row = the one holding 'Week End Date'
    ov_rows = _rows(names["Overview"])
    hi = next((k for k, r in enumerate(ov_rows) if any(_clean(c) == "Week End Date" for c in r)), None)
    if hi is None:
        raise ValueError(f"{path.name}: Overview has no 'Week End Date' header")
    hdr = _header_index(ov_rows[hi])
    overview = []
    for r in ov_rows[hi + 1:]:
        wk = r[hdr["Week End Date"]] if len(r) > hdr["Week End Date"] else None
        if not isinstance(wk, (dt.date, dt.datetime)):
            continue
        rec = {k: r[x] for k, x in hdr.items() if x < len(r)}
        rec["Week End Date"] = wk.date() if isinstance(wk, dt.datetime) else wk
        overview.append(rec)
    overview.sort(key=lambda o: o["Week End Date"], reverse=True)

    refs = {}
    for r in _rows(names["References"]):
        if r and len(r) > 1 and _clean(r[0]) and _clean(r[1]) and _clean(r[0]) != "Column Name":
            refs[_clean(r[0])] = _clean(r[1])

    fd = file_date(path)
    return SalesVerification(path=path, through=fd - dt.timedelta(days=1) if fd else None,
                             office=office, weeks=weeks, overview=overview, references=refs)


@dataclass
class ComplianceRep:
    name: str
    flags: int
    sales: int
    churn: Dict[str, float]            # '0-30' / '30' / '60' / '90' -> rep %
    campaign: Dict[str, float]         # same keys -> campaign %
    flagged: List[str]                 # which checks tripped


@dataclass
class Compliance:
    path: Path
    week_end: Optional[dt.date]
    reps: List[ComplianceRep]


CHURN_KEYS = ["0-30", "30", "60", "90"]
YES_NO_FLAGS = {"Bill/Ship Addr Match", "SSN On Multiple Orders", "Reused Email Address"}


def read_compliance(path: Path) -> Compliance:
    path = Path(path)
    ws = openpyxl.load_workbook(path, data_only=True, read_only=True).worksheets[0]
    rows = _rows(ws)
    week_end = None
    hi = None
    for k, r in enumerate(rows):
        first = _clean(r[0]) if r else ""
        m = re.match(r"WE (\d{1,2}/\d{1,2}/\d{2})", first)
        if m:
            week_end = dt.datetime.strptime(m.group(1), "%m/%d/%y").date()
        if first == "Sales Agent Name":
            hi = k
            break
    if hi is None:
        raise ValueError(f"{path.name}: no 'Sales Agent Name' header — Credico changed the file")
    hdr = _header_index(rows[hi])
    for need in ("Total Compliance Flags", "Total Sales",
                 *[f"{c} Day % Churn" for c in CHURN_KEYS]):
        if need not in hdr:
            raise ValueError(f"{path.name}: no '{need}' column")
    # Yes/no checks without 'Flag' in the header also count toward Credico's total
    # (Jose Ramos WE 10/31: 4+ lines/order + SSN on multiple orders = his 2).
    flag_cols = [h for h in hdr if (h.endswith("Flag") or h in YES_NO_FLAGS)
                 and h != "Total Compliance Flags"]
    reps = []
    for r in rows[hi + 1:]:
        name = _clean(r[hdr["Sales Agent Name"]]) if r else ""
        if not name:
            continue
        reps.append(ComplianceRep(
            name=name,
            flags=int(_num(r[hdr["Total Compliance Flags"]])),
            sales=int(_num(r[hdr["Total Sales"]])),
            churn={c: _num(r[hdr[f"{c} Day % Churn"]]) for c in CHURN_KEYS},
            campaign={c: _num(r[hdr[f"Campaign {c} Day % Churn"]])
                      for c in CHURN_KEYS if f"Campaign {c} Day % Churn" in hdr},
            flagged=[h.replace(" Flag", "") for h in flag_cols if _num(r[hdr[h]]) >= 1],
        ))
    return Compliance(path=path, week_end=week_end, reps=reps)
