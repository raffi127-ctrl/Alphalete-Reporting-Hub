"""Pull Fiber Lead Penetration % (per owner + national total) for the
Int WoW Report 'Penetration %' table.

Source: ATT Tracker 2.1 - D2D / Fiber Lead Performance (Tableau), the
by-zip Crosstab. Two values come out of the same crosstab:

  * Per-owner penetration  = column 'Office Lead Penetration (Fixed)'.
    This is the owner-level measure, CONSTANT across that owner's zip
    rows (verified 2026-06-02: Sam Park 4.5% on every zip row). It's the
    column the sheet has always used — the broken 514.3% for Zach Hogue
    carried straight into the sheet.
  * National total        = the 'Total general' row's 'Assigned Fiber
    Lead Penetration' (Owner = (All)), per Eve's spec.

The 5.24 backfill is parsed from a manually-downloaded CSV; the weekly
run pulls the same crosstab from Tableau. parse_csv() handles both.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Base Fiber Lead Performance view. The crosstab worksheet name is matched
# rename-tolerantly at download time (opt_phase._match_crosstab_sheet).
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/FiberLeadPerformance?:iid=1")
WORKSHEET = "Office New Fiber Lead Penetration By Zip"

# Column header labels (matched by name, never by index — Tableau reorders).
COL_OWNER = "Account_Owner_Name__c"
COL_OWNER_PCT = "Office Lead Penetration (Fixed)"
COL_ASSIGNED = "Assigned Fiber Lead Penetration"

# A penetration above this is almost certainly a Tableau glitch (the real
# values sit under ~6%); we still write it but warn so Eve catches it.
SANITY_MAX_PCT = 50.0


def fmt_pct(raw: str) -> Optional[str]:
    """'4.5%' -> '4.50%', '0.0%' -> '0.00%', '1.30%' -> '1.30%'. Returns None
    if the cell isn't a parseable percentage (blank / 'N/A')."""
    s = (raw or "").strip().replace(",", "").rstrip("%").strip()
    if not s:
        return None
    try:
        return f"{float(s):.2f}%"
    except ValueError:
        return None


def _decode(path: Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("latin-1", "replace")


def _col_index(header: list[str], label: str) -> int:
    want = label.strip().lower()
    for i, h in enumerate(header):
        if (h or "").strip().lower() == want:
            return i
    raise KeyError(f"Column {label!r} not found in CSV header: {header}")


def parse_csv(path: Path, verbose: bool = True) -> dict:
    """Parse the by-zip Fiber Lead Penetration crosstab.

    Returns {"owners": {owner_name: 'X.XX%'}, "national": 'X.XX%'|None,
             "warnings": [str]}. owner_name is the raw Tableau spelling —
            alias canonicalization happens in the fill step.
    """
    txt = _decode(path)
    first = txt.splitlines()[0] if txt else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.reader(io.StringIO(txt), delimiter=delim))
    if not rows:
        raise ValueError(f"Empty CSV: {path}")

    header = rows[0]
    i_owner = _col_index(header, COL_OWNER)
    i_pct = _col_index(header, COL_OWNER_PCT)
    i_assigned = _col_index(header, COL_ASSIGNED)

    owners: dict[str, str] = {}
    national: Optional[str] = None
    warnings: list[str] = []

    for row in rows[1:]:
        if len(row) <= max(i_owner, i_pct, i_assigned):
            continue
        owner = (row[i_owner] or "").strip()
        pen_label = (row[i_pct] or "").strip()
        # Grand-total row: owner cell == 'Total', pct cell == 'Total general'.
        if owner.lower() == "total" or pen_label.lower() == "total general":
            national = fmt_pct(row[i_assigned])
            continue
        if not owner:
            continue
        pct = fmt_pct(pen_label)
        if pct is None:
            continue  # owner row without a parseable owner-level pct
        if owner not in owners:           # constant per owner — take first
            owners[owner] = pct
            try:
                if abs(float(pct.rstrip("%"))) > SANITY_MAX_PCT:
                    warnings.append(f"{owner}: {pct} (>{SANITY_MAX_PCT:.0f}% — "
                                    f"likely a Tableau glitch)")
            except ValueError:
                pass

    if verbose:
        print(f"  parsed {len(owners)} owners; national={national!r}")
        for w in warnings:
            print(f"  ⚠ {w}")
    if national is None:
        warnings.append("national total ('Total general' row) not found")
    return {"owners": owners, "national": national, "warnings": warnings}


def fetch_crosstab(out_path: Path, verbose: bool = True,
                   page=None) -> Path:
    """Download the Fiber Lead Performance by-zip crosstab CSV from Tableau."""
    return download_crosstab_patchright(VIEW_URL, WORKSHEET, out_path,
                                        verbose=verbose, page=page)


def fetch_and_parse(out_path: Path, verbose: bool = True, page=None) -> dict:
    csv_path = fetch_crosstab(out_path, verbose=verbose, page=page)
    if verbose:
        print(f"  ✓ {csv_path}")
    return parse_csv(csv_path, verbose=verbose)
