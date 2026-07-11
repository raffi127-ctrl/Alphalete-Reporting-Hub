"""Pull the New Internet ABP (Auto Bill Pay) mix for Raf's Local Office.

Source (Twaddle's Loom, 2026-07-10): Tableau → 'Metrics' tab (Chris
Wilford) in the ATT TRACKER 2.1 - D2D workbook — the SAME workbook the
Churn report pulls from. The RafLocalofficeINTABP custom view bakes in
the ICD Owner Name = RAFAEL HIDALGO filter and drills to per-rep data.

Unlike the Churn crosstab (metric-type rows pivoted into periods), the
ABP crosstab is a FLAT wide table — one row per rep, every metric its
own column. We only need two of them per rep:

    'New Internet Count (Metrics)'        → total new-internet sales (denom)
    'New Internet ABP Mix % (Metrics)'    → the ABP % itself

ABP sale count isn't a column, so we derive it: round(denom * pct/100).
That recovers the integer count cleanly because the mix % was itself
computed from integer counts (verified against the 2026-07-10 pull:
Kushpit 5 * 60% = 3, Abel 3 * 66.7% = 2, office 124 * 87.1% = 108).

parse() returns:
    {
      "office_total": {"pct": "87.1%", "num": 108, "denom": 124},
      "reps": {
          "Abel Mireles": {"pct": "66.7%", "num": 2, "denom": 3},
          ...
      },
    }
"""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

VIEW_URL = os.environ.get("ABP_NI_VIEW_URL") or (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics/"
    "07afddc4-36b3-4ecc-98a8-28b9ef1648c1/RafLocalofficeINTABP?:iid=1"
)
# The only data worksheet in the view (the other is 'zzz Last Refresh
# speedtest'). Verified via the Crosstab dialog enumeration 2026-07-10.
WORKSHEET = "Metrics Call Last week data (Internet)"

# Owner filter value (col 'ICD Owner Name (rep)'). Override per office —
# Rashad's wrapper sets ABP_OWNER="RASHAD REED" (matched case-insensitively).
OWNER = os.environ.get("ABP_OWNER", "RAFAEL HIDALGO")
COUNT_COL = "New Internet Count (Metrics)"
PCT_COL = "New Internet ABP Mix % (Metrics)"
OWNER_COL = "ICD Owner Name (rep)"
REP_COL = "Rep Name"


def fetch_crosstab(out_path: Optional[Path] = None,
                   verbose: bool = False,
                   page=None,
                   view_url: Optional[str] = None) -> Path:
    """Download the ABP Crosstab. Pass `page` to reuse an existing
    tableau_session (mirrors churn's shared-session pattern). Pass
    `view_url` to override the office's view (the combined runner uses
    this to pull Raf + Rashad under one session without env crosstalk)."""
    out_path = out_path or (
        Path(tempfile.gettempdir()) / "new_internet_abp_local_office.csv")
    download_crosstab_patchright(view_url or VIEW_URL, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


def _to_int(v: str) -> Optional[int]:
    v = (v or "").strip().replace(",", "")
    if not v:
        return None
    try:
        return int(round(float(v)))
    except ValueError:
        return None


def parse(csv_path: Path, owner: Optional[str] = None) -> dict:
    """Pivot the flat ABP crosstab into office + per-rep {pct, num, denom}.
    `owner` overrides the ICD-Owner filter for this parse (the combined
    runner passes each office's owner explicitly so one process can parse
    both Raf's + Rashad's CSVs with no reliance on the ABP_OWNER global)."""
    owner = (owner or OWNER)
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    for col in (OWNER_COL, REP_COL, COUNT_COL, PCT_COL):
        if col not in header:
            raise ValueError(
                f"Column {col!r} missing from ABP crosstab header {header}. "
                "The Tableau view schema changed.")
    oi = header.index(OWNER_COL)
    ri = header.index(REP_COL)
    ci = header.index(COUNT_COL)
    pi = header.index(PCT_COL)

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(oi, ri, ci, pi):
            continue
        row_owner = r[oi].strip()
        rep = r[ri].strip()
        pct = r[pi].strip()
        denom = _to_int(r[ci])

        # The office roll-up rows carry Rep Name == 'Total'. The one under
        # our owner is the office total; take it once. Owner match is
        # case-insensitive so ABP_OWNER can be given in any case.
        owner_match = row_owner.upper() == owner.upper()
        if rep == "Total":
            if owner_match and not office_total:
                office_total = _slot(pct, denom)
            continue
        # Per-rep rows are those under our owner filter.
        if not owner_match:
            continue
        if not rep:
            continue
        reps[rep] = _slot(pct, denom)

    return {"office_total": office_total, "reps": reps}


def _slot(pct: str, denom: Optional[int]) -> dict:
    """Build a {pct, num, denom} slot. num (ABP count) is derived from
    denom * pct. A blank pct means 'no data' — slot carries no pct so the
    fill leaves the cell blank (matches churn's 'no entry' semantics)."""
    pct = (pct or "").strip()
    if not pct:
        return {}
    slot: dict = {"pct": pct, "denom": denom}
    try:
        pv = float(pct.replace("%", ""))
    except ValueError:
        return slot
    if denom is not None:
        slot["num"] = int(round(denom * pv / 100.0))
    return slot


def fmt_units(slot: Optional[dict]) -> str:
    """Format a slot's ABP/total as 'N/D' for the units column. Blank when
    either side is missing (keeps the cell empty = 'no data')."""
    if not slot:
        return ""
    num = slot.get("num")
    denom = slot.get("denom")
    if num is None or denom is None:
        return ""
    return f"{int(num):,}/{int(denom):,}"


def has_pct(slot: Optional[dict]) -> bool:
    """True if the slot carries any ABP % — including an explicit 0%
    (0% is DATA: the rep sold but none on AutoPay). Mirrors churn's
    _has_pct visibility rule."""
    return bool(slot and (slot.get("pct") or "").strip())
