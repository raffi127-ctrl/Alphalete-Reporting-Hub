"""Tableau extractors for the Fiber Activations Report.

Three sources from the Captain's Bonus dashboard (one URL, several
worksheets in the Crosstab dialog):

- CB Activations (<team>) — daily breakdown + Total Activations per team
- CB Appr + Churn (Raf) — 60-Day New Internet Churn Rate + Rolling 4 Weeks

The dashboard returns the current week's running cumulative as the
'Grand Total' row. Run this daily; the snapshot we pull at time-of-run
is what gets written into today's day-of-week column on the sheet.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Captain's Bonus custom view (AUTOMATIONPULL-NICHURNVIEW). The Weekending
# URL param is REQUIRED — without it, Crosstab returns the underlying
# worksheet's full data range (last completed week, ~3,000 activations)
# instead of the dashboard-filtered current week. Param name verified
# 2026-05-27: 'Weekending' works; 'Week Ending', 'Sale Date Week End',
# 'Weekending Date' all silently no-op.
CB_VIEW_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CaptainsBonus/4ad1e1ef-9e3c-40cb-9f9c-858195ee57ee/"
    "AUTOMATIONPULL-NICHURNVIEW?:iid=1&Weekending={weekending}"
)

# PRODUCT SALES SUMMARY 4WK ALLREPS custom view. Filter names from DOM probe:
# 'Sale Date Week Ending (mon-sun)' selects the WE Sunday;
# 'Captain%27s Bonus Teams v2' filters by captainship.
# Y94 (Country EOW): no team filter, then subtract UPGRADE INTERNET leaves.
# I94 (Raf EOW):     Captain's Bonus Teams v2 = Raf's Team, read Sales Total as-is.
PSS_VIEW_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
    "3a00519d-9219-4991-919b-7e084d56fc21/ALLREPS?:iid=1"
    "&Sale%20Date%20Week%20Ending%20(mon-sun)={we_sunday}"
)
PSS_RAF_TEAM_PARAM = "&Captain%27s%20Bonus%20Teams%20v2=Raf%27s%20Team"
PSS_WORKSHEET = "Sales By ICD (Weekly View)"

# Product Type URL filter: pass each desired value as a separate param so
# Tableau computes Sales Total *with the filter active at source* (vs. our
# subtract-post-hoc approach which under-counted by ~34 due to AIR/VOICE
# rows aggregating differently). 5 product types = everything except
# UPGRADE INTERNET for Y col.
_PT_KEY = "Product%20Type%20(Broken%20Out)"
PSS_PT_NO_UPGRADE = (
    f"&{_PT_KEY}=AIR&{_PT_KEY}=NEW%20INTERNET&{_PT_KEY}=VIDEO"
    f"&{_PT_KEY}=VOICE&{_PT_KEY}=WIRELESS"
)
PSS_PT_ALL = PSS_PT_NO_UPGRADE + f"&{_PT_KEY}=UPGRADE%20INTERNET"


def cycle_sunday(today) -> "datetime.date":
    """Sunday of the Wed-Tue cycle containing today (= sheet WE column value)."""
    import datetime as dt
    days_since_wed = (today.weekday() - 2) % 7
    cycle_wed = today - dt.timedelta(days=days_since_wed)
    return cycle_wed + dt.timedelta(days=4)


def cycle_saturday(today) -> "datetime.date":
    """Saturday of the Wed-Tue cycle containing `today`. The Captain's Bonus
    dashboard's Weekending filter uses Saturday of each cycle; sheet's WE
    column uses Sunday (off by 1 day from Tableau)."""
    import datetime as dt
    # Days since the cycle's Wednesday: Wed=0, Thu=1, ..., Tue=6.
    days_since_wed = (today.weekday() - 2) % 7
    cycle_wed = today - dt.timedelta(days=days_since_wed)
    return cycle_wed + dt.timedelta(days=3)


def build_cb_url(today) -> str:
    return CB_VIEW_URL_TMPL.format(weekending=cycle_saturday(today).isoformat())

TEAMS = ["Aron", "Pat", "Raf", "Starr", "Wayne"]

# Wayne's worksheet uses 'Grand Total' as its totals column header
# instead of 'Total Activations' — extractor tries both.
_TOTAL_COL_CANDIDATES = ("Total Activations", "Grand Total")

DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


@dataclass
class TeamActivations:
    team: str
    grand_total: int
    per_day: Dict[str, int] = field(default_factory=dict)


@dataclass
class FiberActivationsPull:
    teams: Dict[str, TeamActivations] = field(default_factory=dict)
    raf_60d_churn: Optional[str] = None     # raw string, e.g. "5.94%"
    raf_rolling_4w: Optional[str] = None    # raw string, e.g. "80.0%"
    raf_eow_sales: Optional[int] = None     # PSS Sales Total, Raf-team filtered (I94)
    country_eow_sales: Optional[int] = None # PSS Sales Total minus UPGRADE leaves (Y94)

    @property
    def country_grand_total(self) -> int:
        return sum(t.grand_total for t in self.teams.values())

    @property
    def country_per_day(self) -> Dict[str, int]:
        out = {d: 0 for d in DAYS}
        for t in self.teams.values():
            for d, v in t.per_day.items():
                out[d] = out.get(d, 0) + v
        return out


def _read_crosstab(path: Path):
    with open(path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Empty crosstab at {path}")
    # strip BOM from first header cell
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    cols = {h: i for i, h in enumerate(header)}
    grand = rows[1]
    return header, grand, cols


def _parse_int(s: str) -> int:
    s = (s or "").replace(",", "").strip()
    return int(s) if s else 0


def _extract_team_activations(path: Path, team: str) -> TeamActivations:
    header, grand, cols = _read_crosstab(path)
    total_col = next((c for c in _TOTAL_COL_CANDIDATES if c in cols), None)
    if total_col is None:
        raise RuntimeError(
            f"Could not find totals column on {team} sheet; header={header}"
        )
    grand_total = _parse_int(grand[cols[total_col]])
    per_day = {}
    for d in DAYS:
        if d in cols:
            per_day[d] = _parse_int(grand[cols[d]])
    return TeamActivations(team=team, grand_total=grand_total, per_day=per_day)


def _extract_appr_churn(path: Path) -> tuple[str, str]:
    header, grand, cols = _read_crosstab(path)
    churn_col = cols.get("60 Day New Internet Churn Rate")
    rolling_col = cols.get("Rolling 4 Weeks")
    if churn_col is None or rolling_col is None:
        raise RuntimeError(
            f"CB Appr+Churn missing expected columns; header={header}"
        )
    return grand[churn_col].strip(), grand[rolling_col].strip()


def _extract_pss_sales_total(path: Path, exclude_upgrade: bool) -> int:
    """Read the Sales By ICD (Weekly View) Crosstab — row 1 is the Sales Total
    row, last column is Product Total. If exclude_upgrade=True, subtract the
    UPGRADE INTERNET leaf rows' Product Total contributions."""
    with open(path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    prod_idx = header.index("Product Type (Broken Out)")
    pt_idx = len(header) - 1  # Product Total is the last col
    sales_total = _parse_int(rows[1][pt_idx])
    if not exclude_upgrade:
        return sales_total
    upgrade = 0
    for r in rows[2:]:
        if len(r) <= pt_idx:
            continue
        if r[prod_idx].strip() == "UPGRADE INTERNET":
            upgrade += _parse_int(r[pt_idx])
    return sales_total - upgrade


def pull_all(today, scratch_dir: Optional[Path] = None, verbose: bool = False) -> FiberActivationsPull:
    """Single-session pull: opens patchright once, downloads all 6 crosstabs.

    `today` is the date driving the Weekending URL filter (the Saturday of
    today's Wed-Tue cycle is computed automatically). Returns a
    FiberActivationsPull with per-team activations + Raf's churn/rolling-4w.
    Caller is responsible for sheet writes.
    """
    scratch_dir = scratch_dir or Path("/tmp")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    url = build_cb_url(today)
    result = FiberActivationsPull()

    # One fresh patchright session per Crosstab download. Slower (~6 × ~30s
    # = ~3min total) but reliable: sharing one session across multiple
    # downloads triggers a Tableau state bug where the Weekending URL filter
    # silently stops applying on the 3rd+ call (verified 2026-05-27 with
    # Raf: first 2 calls return correct current-week 221, 3rd call returns
    # last-completed-week 3,072). about:blank between calls didn't help —
    # full session restart does.
    for team in TEAMS:
        sheet = f"CB Activations ({team})"
        out = scratch_dir / f"cb_act_{team.lower()}.csv"
        download_crosstab_patchright(url, sheet, out, verbose=verbose)
        result.teams[team] = _extract_team_activations(out, team)

    out = scratch_dir / "cb_apprchurn_raf.csv"
    download_crosstab_patchright(url, "CB Appr + Churn (Raf)", out, verbose=verbose)
    result.raf_60d_churn, result.raf_rolling_4w = _extract_appr_churn(out)

    # --- PRODUCT SALES SUMMARY 4WK (I + Y columns) ---
    # Two pulls of the same worksheet, different team filters. WE Sunday in
    # the URL filter matches the sheet's WE column.
    we_sunday = cycle_sunday(today).isoformat()
    pss_base = PSS_VIEW_URL_TMPL.format(we_sunday=we_sunday)
    # Country pull: filter Product Type to everything except UPGRADE at source.
    pss_country_url = pss_base + PSS_PT_NO_UPGRADE
    # Raf pull: include all product types + Raf's Team.
    pss_raf_url = pss_base + PSS_PT_ALL + PSS_RAF_TEAM_PARAM

    out = scratch_dir / "pss_country.csv"
    download_crosstab_patchright(pss_country_url, PSS_WORKSHEET, out, verbose=verbose)
    # Filter applied at source — read Sales Total directly.
    result.country_eow_sales = _extract_pss_sales_total(out, exclude_upgrade=False)

    out = scratch_dir / "pss_raf.csv"
    download_crosstab_patchright(pss_raf_url, PSS_WORKSHEET, out, verbose=verbose)
    result.raf_eow_sales = _extract_pss_sales_total(out, exclude_upgrade=False)

    return result
