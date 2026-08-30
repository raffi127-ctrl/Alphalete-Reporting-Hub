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

# The EXPANDED view (ALLTEAMSEXP) carries every product in ONE pull, with the
# product as an extra row dimension in column 2. Probed live 2026-08-30:
#
#   Owner & Office | Rep | Product Type (Broken Out) (BYOD/Non BYOD) |
#   30-60 Color Churn (copy) | <unnamed> | 0-30 Day | 30 Day | 60 Day |
#   90 Day | 120 Day
#
# which is the ORIGINAL per-product shape with exactly one column inserted. So
# selecting a product and DROPPING that column hands the D2D parser back the
# byte-identical shape it already reads - no parser change, same as the rename.
PRODUCT_COL = "Product Type (Broken Out) (BYOD/Non BYOD)"

# Each owner/rep block also carries a 'Total' roll-up row alongside its real
# product rows (and the sheet's Grand Total block is all 'Total'). Those are
# NEVER selected - summing a roll-up in with its own parts doubles every number.
PRODUCT_TOTAL = "TOTAL"

# product key -> the Product Type values that make it up. 'wireless' is BOTH
# halves: verified 2026-08-30 by probing the old ALLTEAMWireless view, whose own
# product filter admits exactly {Total, BYOD WIRELESS, NON BYOD WIRELESS}.
PRODUCT_TYPES = {
    "wireless": ("BYOD WIRELESS", "NON BYOD WIRELESS"),
    "new_int": ("NEW INTERNET",),
    "air": ("AIR/AWB",),
}

# Must survive the rename or the parse silently yields nothing.
REQUIRED_AFTER = ("Rep Name", "0-30 Day Churn")

OWNER_WIDE = "ICD Owner Name (rep)"     # post-rename name of the owner column


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


def select_product(rows: List[list], keep: Sequence[str]) -> List[list]:
    """Keep only `keep`'s product rows, then DROP the product column.

    A per-product view has no product column at all, so this is a no-op there —
    which keeps the old three-view path working untouched if it is ever restored.

    FAIL LOUD, for the same reason rename_header does: if the product values are
    renamed in Tableau, silently keeping zero rows would fill the tabs with
    nothing and report success.
    """
    if not rows:
        raise ValueError("empty churn crosstab")
    hdr = [_norm(h).lstrip("\ufeff") for h in rows[0]]
    if PRODUCT_COL not in hdr:
        return rows
    pi = hdr.index(PRODUCT_COL)
    wanted = {str(k).strip().upper() for k in keep}

    def _drop(row):
        return [c for i, c in enumerate(row) if i != pi]

    out = [_drop(rows[0])]
    seen = set()
    for r in rows[1:]:
        val = _norm(r[pi]).upper() if pi < len(r) else ""
        if val:
            seen.add(val)
        if val in wanted:
            out.append(_drop(r))
    if len(out) == 1:
        raise ValueError(
            "churn crosstab has no rows for product(s) {} — the export carries "
            "{}. The Product Type values moved.".format(
                sorted(wanted), sorted(seen) or "nothing"))
    return out


def write_crosstab(rows: Sequence[Sequence[str]], path: Path) -> Path:
    """Write back in the exact format new_internet_churn.pull.parse reads
    (UTF-16LE, tab-delimited), so the parser needs no changes at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-16-le", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rows)
    return path


def normalize_owner(value: str) -> str:
    """'CARLOS HIDALGO [alphalete specialized marketing inc(tx]' -> 'CARLOS HIDALGO'.

    The D2D parser matches its owner slice by EXACT equality:

        if (r[owner_i] or "").strip().upper() != slice_owner.upper(): continue

    D2D's 'ICD Owner Name (rep)' is a bare name, so that works there. B2B's
    'Owner & Office' is a composite 'NAME [company]' (and the member can carry
    an embedded newline before the office suffix). Left as-is, every row fails
    the comparison and the parse yields zero reps — which is exactly what the
    first live run hit (2026-07-19). Strip to the person name so the existing
    exact-match logic works untouched.
    """
    s = _norm(value).split("\n")[0]
    if "[" in s:
        s = s.split("[", 1)[0]
    return s.strip()


def normalize_owner_column(rows: List[list]) -> List[list]:
    """Apply normalize_owner to every value in the owner column."""
    if not rows:
        return rows
    hdr = [_norm(h) for h in rows[0]]
    if OWNER_WIDE not in hdr:
        return rows
    oi = hdr.index(OWNER_WIDE)
    out = [rows[0]]
    for r in rows[1:]:
        r = list(r)
        if oi < len(r):
            r[oi] = normalize_owner(r[oi])
        out.append(r)
    return out


# The metric-type value the D2D parser keys the churn % off. B2B labels it
# plainly "Churn Rate"; D2D's parse matches the EXACT string
# "Churn Rate (Unit vs Order)" and sets slot["pct"] only on that match. Unmapped
# => no pct => _has_pct False => insert_missing_reps adds nobody => write_today
# writes nothing => exit 0 with an empty tab. That is exactly what happened
# (2026-07-20): "parsed 70 reps, wrote", 12 rows. The other two metric labels
# ("Activated SPE/SP", "Disconnect count (SPE/SP)") already match, so only this
# one is remapped.
METRIC_RENAME = {"Churn Rate": "Churn Rate (Unit vs Order)"}


def normalize_metric_column(rows: List[list]) -> List[list]:
    """Remap metric-type labels in the unnamed column just left of the first
    '<period> Day Churn' column — the same column the parser reads as metric_i.
    Located positionally (not by header) because that column has no header."""
    if not rows:
        return rows
    hdr = [_norm(h) for h in rows[0]]
    period_idx = [i for i, h in enumerate(hdr) if h.endswith("Day Churn")]
    if not period_idx:
        return rows
    mi = min(period_idx) - 1
    if mi < 0:
        return rows
    out = [rows[0]]
    for r in rows[1:]:
        r = list(r)
        if mi < len(r):
            r[mi] = METRIC_RENAME.get(_norm(r[mi]), r[mi])
        out.append(r)
    return out


def adapt(src: Path, dest: Path, keep: Sequence[str] = None) -> Dict[str, object]:
    """Read the B2B crosstab, rename its header, normalize the owner + metric
    columns, and write a D2D-shaped file.

    `keep` selects one product family out of the expanded all-products view; omit
    it for a view that is already filtered to a single product."""
    rows = read_crosstab(src)
    if keep:
        rows = select_product(rows, keep)
    renamed = rename_header(rows)
    renamed = normalize_owner_column(renamed)
    renamed = normalize_metric_column(renamed)
    write_crosstab(renamed, dest)
    hdr = renamed[0]
    owners = []
    if OWNER_WIDE in hdr:
        oi = hdr.index(OWNER_WIDE)
        owners = sorted({_norm(r[oi]) for r in renamed[1:]
                         if oi < len(r) and _norm(r[oi])})
    return {
        "rows": len(renamed) - 1,
        "renamed": [h for h in RENAME if h in
                    [_norm(x).lstrip("﻿") for x in rows[0]]],
        "periods": [h for h in hdr if h.endswith("Day Churn")],
        "owners": owners[:8],
        "dest": str(dest),
    }
