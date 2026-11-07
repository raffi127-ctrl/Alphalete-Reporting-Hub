"""Verizon OPT — the weekly OPT numbers for a Verizon ICD's tab, from Credico.

    python -m automations.alphalete_org_report.opt_verizon --sv FILE.xlsx            # preview
    python -m automations.alphalete_org_report.opt_verizon --office nicolas          # newest from the Hub inbox

PREVIEW ONLY. There is no "<Owner> - Verizon" tab yet and its rows are Megan's
to pick; nothing here writes a sheet (and Megan 2026-11-06: nothing live until
Nico is on ECO). When the tab exists, a fill looks rows up BY LABEL
(feedback: no hardcoded rows) using the labels below.

SOURCE: Credico's daily "Sales Verification" xlsx -> 'Overview' sheet, one row
per Credico sales week (Sun-Sat). Credico's week ending SATURDAY maps to the
sheet's week ending the NEXT SUNDAY, as Frontier's does (opt_frontier: "5/16
-> 5/17").

Every value is Credico's own number or a plain ratio of two of them; Credico's
definition of each column is in the same file's 'References' sheet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# (OPT row label, Overview column, kind) -- kind: "n" count, "pct" share 0-1
ROWS: List[Tuple[str, str, str]] = [
    ("Active Selling Heads", "Scoring HC", "n"),
    ("Total Verizon Lines", "Valid Lines", "n"),
    ("Lines per Rep", None, "ratio"),            # Valid Lines / Scoring HC
    ("Submitted %", "% Sub.", "pct"),
    ("Activated %", "% Total Acts.", "pct"),
    ("Approved %", "% Appr.", "pct"),
    ("Canceled %", "% Canc.", "pct"),
    ("Disconnected %", "% Disc.", "pct"),
    ("AutoPay %", "AutoPay %", "pct"),
    ("BYOD %", "BYOD %", "pct"),
    ("Port-In %", "Port-In %", "pct"),
    ("Unlimited Plus+ %", "UPlus+ %", "pct"),
    ("Insured %", "Insured %", "pct"),
    ("Paid On %", "% Paid On", "pct"),
]


def sheet_week(credico_week_end: dt.date) -> dt.date:
    """Credico Sat -> the sheet's Sunday column (the next day)."""
    return credico_week_end + dt.timedelta(days=1)


def values_for(overview_row: Dict) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for label, col, kind in ROWS:
        if kind == "ratio":
            hc, lines = overview_row.get("Scoring HC"), overview_row.get("Valid Lines")
            try:
                out[label] = round(float(lines) / float(hc), 1) if float(hc) else None
            except (TypeError, ValueError):
                out[label] = None
            continue
        v = overview_row.get(col)
        try:
            out[label] = float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            out[label] = None
    return out


def fmt(label: str, v: Optional[float]) -> str:
    if v is None:
        return "— (blank in Credico: flagged, not 0)"
    kind = next(k for l, _c, k in ROWS if l == label)
    return f"{v*100:.1f}%" if kind == "pct" else (f"{v:g}")


def weeks(sv_path: Path, n: int = 4) -> List[Tuple[dt.date, Dict[str, Optional[float]]]]:
    from automations.verizon_office import parse
    sv = parse.read_sales_verification(sv_path)
    return [(sheet_week(o["Week End Date"]), values_for(o)) for o in sv.overview[:n]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, help="local Sales Verification xlsx")
    ap.add_argument("--office", help="verizon_office key (newest file from the Hub inbox)")
    ap.add_argument("--weeks", type=int, default=4)
    a = ap.parse_args(argv)
    path = a.sv
    if not path and a.office:
        from automations.verizon_office import offices as OF, run as RUN
        path = RUN.fetch(OF.get(a.office), "sales")
    if not path:
        ap.error("give --sv FILE or --office KEY (no Sales Verification found)")
    rows = weeks(path, a.weeks)
    if not rows:
        print("✗ no weeks in the Overview sheet — nothing to show")
        return 1
    print("Verizon OPT preview — %s (nothing written)\n" % Path(path).name)
    head = "%-22s" % "Row" + "".join("%14s" % ("WE " + w.strftime("%-m/%-d")) for w, _ in rows)
    print(head)
    for label, _c, _k in ROWS:
        print("%-22s" % label + "".join("%14s" % fmt(label, vals[label]).split(" (")[0] for _w, vals in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
