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

# ALLEXP = Megan's all-owners, "This Week", REP-ROWS-EXPANDED custom view
# (saved 2026-08-07). Switched here because the Metrics worksheet was rebuilt
# and now COLLAPSES to ICD-Owner level by default — the crosstab drops the
# 'Rep Name' column entirely unless the rep hierarchy is expanded (hit the '+'
# above the ICD name). The old RafLocalofficeINTABP view rode that collapsed
# state, so every ABP pull started coming back owner-only and the parse died on
# a missing 'Rep Name'. ALLEXP bakes the expansion + the This-Week (running
# week-to-date, so the daily card keeps its day-over-day movement) param into
# the saved view; it's all-owners, and parse() self-filters to OWNER, so one
# view serves every office — office_metrics points ALL_OFFICE_ABP_VIEW here too.
# (If it ever drifts back to collapsed, re-save ALLEXP with the rep '+'
# expanded, on This Week — same fix.)
VIEW_URL = os.environ.get("ABP_NI_VIEW_URL") or (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics/"
    "0d5c97aa-d39e-4541-bf88-a8e599ab5e69/ALLEXP?:iid=1"
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


# --- Fallback: owner missing from the Metrics view → the Order Log ------------
# Some owners exist in the org Order Log but NOT in the Metrics data source (Lala
# / Lajahnik Valentine, new from Lumen with no captainship: absent from ALLEXP on
# 2026-10-10, so ABP had nothing to fill). The ORDERLOG ALLREPS view — same ATT
# TRACKER 2.1 workbook — carries 'Auto Bill Pay' Y/N on every order, so the mix
# can be rebuilt from it. PROVEN 2026-10-10 against that day's ALLEXP: counting
# NEW INTERNET orders with an order date Mon→today (every status — cancels
# included) reproduced Tableau's count AND % for 64/65 offices and 976/977 reps;
# the one miss was an order placed that morning, past the then-yesterday end date
# (so this pull ends TODAY). A different window (Sunday start, cancels dropped)
# matched ≤25/65 — don't "tidy" either rule.
ORDER_LOG_SHEET = "A.Order Log"
ORDER_LOG_VIEW_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/ORDERLOG/"
    "117748c0-9487-45e8-a5d4-c447093718d5/ALLREPS?:iid=1"
    "&Start%20Date={start}&End%20Date={end}"
)


def owner_in_view(csv_path: Path, owner: Optional[str] = None) -> bool:
    """True if the Metrics crosstab has ANY row for this owner — the line
    between 'this office sold nothing' and 'this office isn't in the view'."""
    owner = (owner or OWNER).upper()
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return False
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    if OWNER_COL not in header:
        return False
    oi = header.index(OWNER_COL)
    return any(len(r) > oi and r[oi].strip().upper() == owner for r in rows[1:])


def fetch_order_log(today, out_path: Optional[Path] = None,
                    verbose: bool = False) -> Path:
    """The org-wide Order Log crosstab for this ABP week (Monday → today)."""
    import datetime as _dt
    monday = today - _dt.timedelta(days=today.weekday())
    out_path = out_path or (
        Path(tempfile.gettempdir()) / "new_internet_abp_order_log.csv")
    url = ORDER_LOG_VIEW_TMPL.format(start=monday.isoformat(),
                                     end=today.isoformat())
    download_crosstab_patchright(url, ORDER_LOG_SHEET, out_path,
                                 verbose=verbose)
    return out_path


def parse_order_log(csv_path: Path, today, owner: Optional[str] = None) -> dict:
    """Same shape as parse(), rebuilt from Order Log rows (see the proof above)."""
    import datetime as _dt
    owner = (owner or OWNER).upper()
    monday = today - _dt.timedelta(days=today.weekday())
    with open(csv_path, "r", encoding="utf-16") as f:
        lines = list(csv.reader(f, delimiter="\t"))
    hi = next((i for i, r in enumerate(lines)
               if any(c.strip().strip('"') == "Owner Name" for c in r)), None)
    if hi is None:
        return {"office_total": {}, "reps": {}}
    header = [c.strip().strip('"').lstrip("﻿") for c in lines[hi]]
    for col in ("Owner Name", "Rep", "sp.Order Date (copy)",
                "Product Type (Broken Out)", "Auto Bill Pay"):
        if col not in header:
            raise ValueError(f"Column {col!r} missing from Order Log header "
                             f"{header}. The Tableau view schema changed.")
    oi, ri = header.index("Owner Name"), header.index("Rep")
    di = header.index("sp.Order Date (copy)")
    pti = header.index("Product Type (Broken Out)")
    ai = header.index("Auto Bill Pay")
    need = max(oi, ri, di, pti, ai)
    counts: dict = {}
    for r in lines[hi + 1:]:
        if len(r) <= need or r[oi].strip().upper() != owner:
            continue
        if r[pti].strip().upper() != "NEW INTERNET":
            continue
        try:
            od = _dt.datetime.strptime(r[di].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if not (monday <= od <= today):
            continue
        rep = r[ri].strip()
        if not rep:
            continue
        c = counts.setdefault(rep, [0, 0])
        c[0] += 1
        c[1] += r[ai].strip().upper() == "Y"

    def slot(n: int, y: int) -> dict:
        return {"pct": f"{100.0 * y / n:.1f}%", "num": y, "denom": n}

    reps = {rep: slot(n, y) for rep, (n, y) in counts.items()}
    tn = sum(n for n, _ in counts.values())
    ty = sum(y for _, y in counts.values())
    return {"office_total": slot(tn, ty) if tn else {}, "reps": reps}
