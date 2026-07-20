"""Turn the raw ATTTRACKER-B2B ORDERLOG export into one row per real sale.

TWO distinct problems, often confused. Both must be solved, in this order:

1. MERGED ROW HEADERS (what Carlos describes on the Loom). Tableau merges the
   account-level cells that span an account's product lines, so a download
   leaves them blank on continuation rows: "the order date and the customer
   name, those will need to be dropped down, unmerged and copied and pasted
   down… and then the SPM number". vantura_churn.compute._load_grid already
   back-fills these for BOTH export formats, so we reuse it rather than
   re-implement it.

2. THE MEASURE PIVOT (which the Loom does NOT mention, and which the screenshot
   cannot show). The export emits each real order line ONCE PER MEASURE. Proven
   on the 2026-07-19 Lucy 2 probe:

       group sizes histogram: [(4, 55295), (8, 968)]
       varies: 'Measure Names'  -> Unit Count, Total Volume,
                                   Total Activations, Sales (All) (non pmts) (60-120)
       varies: 'Measure Values' -> 1, 1, 0, 0
       -> 55295*4 + 968*8 == 228924 raw rows == the full export, exactly.

   So ~228.9k raw rows are ~57.2k real order lines. Nothing in
   compute.load_orderlog collapses this — it returns one dict per RAW row.
   vantura_churn survives that only because everything downstream dedupes
   (_churn_units on (product, spe), helper_block on (prod, customer, ban)).
   A row-per-sale log has no such safety net: rendered as-is, every sale
   appears four times.

   The measures are real per-line data, so we PIVOT them into columns rather
   than throwing three rows away.

The 8-row groups are the interesting case: a group of 2*M means two genuinely
distinct sale lines that happen to agree on every non-measure column. They are
emitted as TWO lines, not collapsed into one — see _unpivot.
"""
from __future__ import annotations

import collections
from typing import Dict, List, Optional, Sequence

from automations.vantura_churn import compute

# The pivot columns. Anything not in here is part of a line's identity.
MEASURE_NAME_COL = "Measure Names"
MEASURE_VALUE_COL = "Measure Values"


def _norm(v) -> str:
    return "" if v is None else str(v).strip()


def load_grid(path) -> List[list]:
    """Read an export into a cell grid, whichever shape it arrives in.

    THREE formats reach this module and they are not interchangeable:
      * .xlsx           — the manual download. Merged row-header cells.
      * TAB-delimited   — the crosstab download (usually UTF-16). Row headers
                          blanked on continuation rows.
      * COMMA-delimited — the DIRECT .csv endpoint (UTF-8), which is what
                          run.py pulls.

    compute._load_grid handles the first two only; handed a comma CSV it splits
    nothing and returns one giant column per line. That is not hypothetical —
    it silently produced "481 sales" from 241 rows in testing, with every
    column reported missing. So: delegate xlsx and tab to compute (its
    merged-cell and back-fill logic is proven), and handle comma here with the
    same continuation back-fill applied.
    """
    from pathlib import Path as _P
    p = _P(path)
    with open(p, "rb") as f:
        head = f.read(4)
    if head[:2] == b"PK":                       # xlsx — merged cells
        return compute._load_grid(p)

    rows = None
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            with open(p, encoding=enc, newline="") as fh:
                sample = fh.read(65536)
            if not sample:
                continue
            first = sample.splitlines()[0] if sample.splitlines() else ""
            delim = "\t" if first.count("\t") > first.count(",") else ","
            import csv as _csv
            with open(p, encoding=enc, newline="") as fh:
                rows = list(_csv.reader(fh, delimiter=delim))
            if rows and len(rows[0]) > 1:
                break
            rows = None
        except (UnicodeError, OSError):
            continue
    if not rows:
        raise RuntimeError("could not parse the Order Log export at {}".format(p))

    # Back-fill the merged/blanked row-header columns (problem 1). Same set
    # compute uses, resolved by LABEL so a column move doesn't shift it.
    hdr = [_norm(h).lstrip("﻿") for h in rows[0]]
    gidx = [hdr.index(compute.COLS[k]) for k in compute._GROUP_COLS
            if compute.COLS.get(k) in hdr]
    prev: Dict[int, str] = {}
    for r in rows[1:]:
        for ci in gidx:
            if ci < len(r) and _norm(r[ci]):
                prev[ci] = r[ci]
            elif ci in prev:
                if ci >= len(r):
                    r.extend([""] * (ci - len(r) + 1))
                r[ci] = prev[ci]
    return rows


def load_rows(path, owner_prefix: Optional[str] = None) -> List[dict]:
    """Raw export -> one dict per REAL order line, measures as columns.

    owner_prefix filters to one ICD owner (the Owner & Office cell carries an
    embedded newline before the office suffix, so we match the person-name
    prefix only — same rule as compute.load_orderlog).
    """
    grid = load_grid(path)                   # solves problem 1 (merged headers)
    if not grid:
        raise RuntimeError("Order Log export is empty")
    hdr = [_norm(h).lstrip("﻿") for h in grid[0]]
    return _unpivot(hdr, grid[1:], owner_prefix)          # solves problem 2


def _unpivot(hdr: Sequence[str], rows, owner_prefix: Optional[str]) -> List[dict]:
    """Collapse the per-measure row fan-out back into one row per sale."""
    if MEASURE_NAME_COL not in hdr:
        # Not pivoted (a differently-configured export). Pass rows through so
        # a schema change degrades to "no un-pivot" rather than to garbage.
        return [_as_dict(hdr, r) for r in rows
                if _keep(hdr, r, owner_prefix)]

    mi = hdr.index(MEASURE_NAME_COL)
    vi = hdr.index(MEASURE_VALUE_COL) if MEASURE_VALUE_COL in hdr else None
    # A line's identity = every column except the two pivot columns. Using the
    # full remainder (rather than a hand-picked key like SPM+BAN) is deliberate:
    # a hand-picked key silently merges lines that differ in a column we forgot,
    # and the whole point of this module is to not lose sales.
    key_ix = [i for i in range(len(hdr)) if i not in (mi, vi)]

    ncol = len(hdr)
    groups: "collections.OrderedDict[tuple, dict]" = collections.OrderedDict()
    for r in rows:
        if len(r) < ncol:                    # CSV rows can be ragged
            r = list(r) + [""] * (ncol - len(r))
        if not _keep(hdr, r, owner_prefix):
            continue
        key = tuple(_norm(r[i]) for i in key_ix)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"row": r, "measures": []}
        g["measures"].append((_norm(r[mi]),
                              _norm(r[vi]) if vi is not None else ""))

    # How many measures make up ONE line. Taken from the data (the modal group
    # size) rather than hardcoded to 4: if Tableau gains or loses a measure,
    # a hardcoded 4 would start splitting or merging every sale silently.
    sizes = collections.Counter(len(g["measures"]) for g in groups.values())
    m = min(sizes) if sizes else 1
    if m < 1:
        m = 1

    out: List[dict] = []
    for key, g in groups.items():
        meas = g["measures"]
        # A group of k*m == k real lines that agree on every non-measure
        # column. Emit k of them; do NOT collapse to one (that would drop
        # real sales). A ragged group that isn't a clean multiple is emitted
        # once and flagged, so it surfaces instead of being silently reshaped.
        n_lines, rem = divmod(len(meas), m)
        rec = _as_dict(hdr, g["row"])
        for name, val in meas[:m]:
            if name:
                rec[name] = val
        rec["_measure_rows"] = len(meas)
        rec["_ragged"] = bool(rem)
        for _ in range(max(1, n_lines)):
            out.append(dict(rec))
    return out


def _keep(hdr, r, owner_prefix: Optional[str]) -> bool:
    """Owner filter + drop Grand Total / blank-owner rows."""
    oc = compute.COLS["owner"]
    if oc not in hdr:
        return True
    i = hdr.index(oc)
    owner = _norm(r[i] if i < len(r) else "").split("\n")[0].strip().upper()
    if not owner or owner.startswith("GRAND TOTAL"):
        return False
    if owner_prefix and not owner.startswith(owner_prefix.upper()):
        return False
    return True


def _as_dict(hdr, r) -> dict:
    return {h: _norm(r[i]) if i < len(r) else "" for i, h in enumerate(hdr)}


def stats(lines: List[dict]) -> Dict[str, int]:
    """Counts worth printing on every run — a silent change in these is the
    first sign the export's shape moved under us."""
    return {
        "lines": len(lines),
        "ragged": sum(1 for l in lines if l.get("_ragged")),
    }
