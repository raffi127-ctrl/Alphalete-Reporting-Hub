"""Adapt Carlos's B2B churn crosstab to the header names the D2D parser reads.

WHAT THIS IS NOT. An earlier draft reshaped long->wide, based on the CHURNRATES
*dashboard* .csv, which really is long (a "Churn Buckets" column). That export
was a red herring twice over: it ignores custom views (both of Carlos's returned
byte-identical all-teams data) and it is not the shape the crosstab download
produces. Probed 2026-07-19, the crosstab is:

    Owner & Office | Rep | 30-60 Color Churn (copy) | <unnamed> | 0-30 Day | 30 Day | 60 Day | 90 Day | 120 Day

which is STRUCTURALLY IDENTICAL to the D2D crosstab — periods as columns, the
metric as an unnamed row dimension just left of them. Only the NAMES differ. So
this is a header rename, not a transform, and the D2D parser does the real work.

The crosstab dialog also preserves each custom view's filters: CarloWireless
returned 576 rows / 66 reps and CarlosNewINT 408 / 82 — genuinely different
data, which is what makes the two fills possible at all.

WHY RENAME INSTEAD OF PATCHING THE PARSER. new_internet_churn.pull serves eight
live D2D offices. Renaming at the boundary leaves their path byte-identical and
confines every B2B-specific fact to this file, which can be deleted outright if
Tableau ever republishes the B2B view with D2D naming.

FAIL LOUD. If the expected columns are absent, raise. The D2D parser's failure
mode is to find no period columns and return {"office_total": {}, "reps": {}} —
empty, not an error — so the fill would run, write nothing, and report success.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Sequence

# B2B crosstab name -> the name new_internet_churn.pull.parse expects.
# "30-60 Color Churn (copy)" is deliberately absent: the parser matches that one
# by PREFIX (it varies across views), so it already works untouched.
RENAME: Dict[str, str] = {
    "Rep": "Rep Name",
    "Owner & Office": "ICD Owner Name (rep)",
    "0-30 Day": "0-30 Day Churn",
    "30 Day": "30 Day Churn",
    "60 Day": "60 Day Churn",
    "90 Day": "90 Day Churn",
    # "120 Day" is intentionally NOT renamed. The D2D parser reads exactly four
    # periods and Carlos's scaffold tabs have exactly four sections, so the
    # extra bucket is carried through untouched and ignored.
}

# Must survive the rename or the parse silently yields nothing.
REQUIRED_AFTER = ("Rep Name", "0-30 Day Churn")


def _norm(v) -> str:
    return "" if v is None else str(v).strip()


def read_crosstab(path: Path) -> List[list]:
    """Read a Tableau crosstab export (UTF-16LE, tab-delimited)."""
    for enc in ("utf-16-le", "utf-16", "utf-8-sig"):
        try:
            with open(path, "r", encoding=enc) as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except (UnicodeError, OSError):
            continue
    raise ValueError("could not read churn crosstab at {}".format(path))


def rename_header(rows: List[list]) -> List[list]:
    """Apply RENAME to the header row. Exact matches only — a prefix match
    would rewrite '120 Day' into '120 Day Churn' via the '30 Day' rule and
    invent a period the scaffold has no section for."""
    if not rows:
        raise ValueError("empty churn crosstab")
    hdr = [_norm(h).lstrip("﻿") for h in rows[0]]
    out_hdr = [RENAME.get(h, h) for h in hdr]

    missing = [c for c in REQUIRED_AFTER if c not in out_hdr]
    if missing:
        raise ValueError(
            "churn crosstab is missing {} after rename — the export's schema "
            "moved. Header was: {}".format(missing, hdr))
    return [out_hdr] + rows[1:]


def write_crosstab(rows: Sequence[Sequence[str]], path: Path) -> Path:
    """Write back in the exact format new_internet_churn.pull.parse reads
    (UTF-16LE, tab-delimited), so the parser needs no changes at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-16-le", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rows)
    return path


def adapt(src: Path, dest: Path) -> Dict[str, object]:
    """Read the B2B crosstab, rename its header, write a D2D-shaped file."""
    rows = read_crosstab(src)
    renamed = rename_header(rows)
    write_crosstab(renamed, dest)
    hdr = renamed[0]
    return {
        "rows": len(renamed) - 1,
        "renamed": [h for h in RENAME if h in
                    [_norm(x).lstrip("﻿") for x in rows[0]]],
        "periods": [h for h in hdr if h.endswith("Day Churn")],
        "dest": str(dest),
    }
