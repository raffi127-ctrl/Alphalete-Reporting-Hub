"""Phase-2: org-wide pull + Python slice (SHADOW-ONLY, INERT).

Nothing on the live 4am path imports this. See README.md.

The scaling lever (design §7): at 50-100 offices, N per-office saved views =
2*N Tableau pulls that can't dedup — that's what threatens the 8am deadline.
The fix is to pull ONE org-wide view and slice per office in Python.

The design flagged the one real hazard, which the Phase-2 probe CONFIRMED:
  * rep/owner rows slice cleanly (org view is a byte-identical superset), BUT
  * the per-office office-total row does NOT survive an org-wide collapse — the
    org file carries only the org-wide total. It must be RECOMPUTED from the
    sliced rows and match the per-view total cell-for-cell (value AND %-format).

Two crosstab shapes, two slicers:
  * OWNER-KEYED (B2B `Grand Total`, NDS `Office/Organization Average`): the parse
    already keys rows by owner name → `slice_by_owner` selects the office's owner
    rows + recomputes the total.
  * COLUMN-KEYED (D2D NI/Wireless): the parse keys rows by individual `Rep Name`
    and the office identity is the `ICD Owner Name (rep)` COLUMN → `slice_d2d`
    filters the RAW crosstab rows by that column (dropping the org `Total` row),
    then parses + recomputes.

Membership (which owners belong to a captainship) is sourced from the captainship
roster in production, exactly like org_sales_board/captainship.py; these take an
explicit member set / owner value so the proof isolates aggregation from
membership.
"""
from __future__ import annotations

import csv as _csv
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

# Period buckets per workbook.
B2B_PERIODS = ("0-30", "30", "60", "90", "120")
D2D_PERIODS = ("0-30", "30", "60", "90")
NDS_PERIODS = ("0-30", "30", "60", "90")


def _fmt_pct(num: float, denom: float, decimals: int) -> Optional[str]:
    """Format a churn % the way Tableau's crosstab does: percentage to `decimals`
    places, round-half-up, trailing '%'. None for an undefined ratio (denom 0)."""
    if not denom:
        return None
    pct = (Decimal(str(num)) / Decimal(str(denom))) * Decimal(100)
    q = pct.quantize(Decimal("1." + "0" * decimals) if decimals else Decimal("1"),
                     rounding=ROUND_HALF_UP)
    return f"{q}%"


def recompute_office_total(reps: Dict[str, dict], periods: Iterable[str],
                           decimals: int) -> dict:
    """Reconstruct a per-office total row from its sliced rep rows: office
    num/denom per period = column sum of the reps' num/denom; pct = Tableau-
    formatted num/denom. Only emits a period some rep actually reports."""
    total: dict = {}
    for p in periods:
        present = [r[p] for r in reps.values() if p in r]
        if not present:
            continue
        num = sum(c["num"] for c in present if c.get("num") is not None)
        denom = sum(c["denom"] for c in present if c.get("denom") is not None)
        total[p] = {"num": num, "denom": denom, "pct": _fmt_pct(num, denom, decimals)}
    return total


def _read_utf16_tsv(path: Path):
    with open(path, "r", encoding="utf-16-le") as f:
        return list(_csv.reader(f, delimiter="\t"))


def _resolve_col(header, owner_col):
    """owner_col may be an int index or a header name."""
    return owner_col if isinstance(owner_col, int) else header.index(owner_col)


def owner_cells(csv_path: Path, owner_col, total_bare) -> set:
    """The set of FULL owner cells ('NAME\\n[office]') in a per-view crosstab,
    excluding the office-total row. The full cell (incl. the [office] suffix) is
    the identity — bare name is NOT unique across offices (e.g. two 'Kyle Campas'
    under different offices in the org-wide view)."""
    rows = _read_utf16_tsv(csv_path)
    if not rows:
        return set()
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    oi = _resolve_col(header, owner_col)
    cells = set()
    for r in rows[1:]:
        if len(r) <= oi:
            continue
        cell = (r[oi] or "").strip()
        bare = cell.split("\n")[0].strip()
        if bare and bare not in total_bare:
            cells.add(cell)
    return cells


def slice_owner(org_csv_path: Path, member_cells: set, parse_fn: Callable[[Path], dict],
                *, owner_col, periods: Iterable[str], decimals: int,
                total_bare: set) -> dict:
    """Slice an OWNER-KEYED org crosstab (B2B `Grand Total`, NDS
    `Office/Organization Average`) to one office on RAW rows, matching the FULL
    owner cell (name + [office]) so multi-office name collisions can't merge. Drop
    the org-wide total row, parse with the report's real parser, recompute the total.
    """
    rows = _read_utf16_tsv(org_csv_path)
    if not rows:
        return {"office_total": {}, "reps": {}, "_missing_members": list(member_cells),
                "_sliced_rows": 0}
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    oi = _resolve_col(header, owner_col)

    kept = [rows[0]]
    seen = set()
    for r in rows[1:]:
        if len(r) <= oi:
            continue
        cell = (r[oi] or "").strip()
        bare = cell.split("\n")[0].strip()
        if bare in total_bare:
            continue                       # drop the org-wide total row
        if cell in member_cells:
            kept.append(r)
            seen.add(cell)

    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as tf:
        slice_path = Path(tf.name)
    with open(slice_path, "w", encoding="utf-16-le", newline="") as f:
        _csv.writer(f, delimiter="\t").writerows(kept)

    parsed = parse_fn(slice_path)          # office_total {} (total row dropped)
    return {
        "office_total": recompute_office_total(parsed.get("reps", {}), periods, decimals),
        "reps": parsed.get("reps", {}),
        "_missing_members": sorted(member_cells - seen),
        "_sliced_rows": len(kept) - 1,
    }


def slice_d2d(org_csv_path: Path, owner_value: str, parse_fn: Callable[[Path], dict],
              *, periods: Iterable[str] = D2D_PERIODS, decimals: int = 2,
              owner_col: str = "ICD Owner Name (rep)",
              total_label: str = "Total") -> dict:
    """Slice a COLUMN-KEYED D2D org crosstab (INTAllTeams / WirelessAllTeams) to
    one office by filtering the RAW rows on `owner_col` == owner_value, dropping
    the org-wide `Total` row, then parsing + recomputing the office total.

    Operates on raw rows because the D2D parse keys by individual Rep Name and
    discards the owner column — so the office identity must be applied before parse.
    """
    with open(org_csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}, "_missing_members": [], "_sliced_rows": 0}
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    owner_i = header.index(owner_col)
    rep_i = header.index("Rep Name")

    kept = [rows[0]]
    for r in rows[1:]:
        if len(r) <= owner_i:
            continue
        rname = (r[rep_i] or "").strip() if len(r) > rep_i else ""
        if rname == total_label:
            continue                       # drop the org-wide Total row
        if (r[owner_i] or "").strip() == owner_value:
            kept.append(r)

    # Write the slice back out in the SAME encoding the parser reads, then parse
    # with the report's REAL parser — byte-transparent, no parser fork.
    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as tf:
        slice_path = Path(tf.name)
    with open(slice_path, "w", encoding="utf-16-le", newline="") as f:
        w = _csv.writer(f, delimiter="\t")
        w.writerows(kept)

    parsed = parse_fn(slice_path)          # office_total will be {} (Total row dropped)
    reps = parsed.get("reps", {})
    return {
        "office_total": recompute_office_total(reps, periods, decimals),
        "reps": reps,
        "_missing_members": [],
        "_sliced_rows": len(kept) - 1,
    }
