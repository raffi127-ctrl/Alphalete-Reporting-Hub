"""Pull Carlos' B2B team weekly bonus inputs from Tableau.

Source: ATTTRACKER-B2B / CaptainsTeam, the "B2B Leader Recognition" dashboard
(the Loom's "Captain Team"). Filtered to the just-completed week via the
**"Activation Date Week Ending (copy)"** URL param set to that week's SATURDAY
in **ISO (YYYY-MM-DD)** form — M/D/YYYY silently no-ops and leaves the
in-progress week (verified 2026-07-07). Four crosstab worksheets:

  * CB-Owner Sales        -> per-rep **weekly activations** for Carlos' team
                             (+ team total = 808 for WE 2026-07-05).
  * Captain Team Check (2)-> team **Churn Rate (0-30)** + **Activation Rate
                             (31-60)** (Carlos's Team row).
  * Captain Team Check (4)-> team **Non Pmt %** (Carlos's Team row).
  * CB-Owner Metrics      -> Carlos Hidalgo's personal **Churn Rate (0-30)**.

Reuses fiber_activations.pull.cycle_saturday for the week + the patchright
ownerville SSO downloader. One FRESH session per download (page=None): sharing
one session silently drops the week filter on the 3rd+ call.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from automations.fiber_activations import pull as P
from automations.shared.tableau_patchright import download_crosstab_patchright

CACHE_DIR = Path("/tmp/carlos_captainship_bonus")
VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/"
        "CaptainsTeam/15e2f8c1-420b-4ab4-8ce1-49b5d85ab969/B2BLeaderRecognition")
WEEK_FIELD = "Activation%20Date%20Week%20Ending%20(copy)"  # value = Saturday ISO
TEAM = "carlos's team"          # SFDC team label in the crosstabs
CARLOS_OWNER = "carlos hidalgo"  # for the personal 0-30 churn


@dataclass
class CarlosPull:
    reps: Dict[str, int] = field(default_factory=dict)  # {owner lower: activations}
    roster: set = field(default_factory=set)            # current SFDC team members (lower)
    grand_total: int = 0
    churn_team: Optional[str] = None       # "4.2%"  -> row 52
    churn_personal: Optional[str] = None   # "4.4%"  -> row 53
    activation: Optional[str] = None       # "78.2%" -> row 56
    nonpmt: Optional[str] = None           # "2.58%" -> row 58


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _parse_int(s: str) -> int:
    s = (s or "").replace(",", "").strip()
    if s in ("", "-", "–", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _read(path: Path) -> List[List[str]]:
    with open(path, "r", encoding="utf-16-le") as f:
        return [[c.lstrip("﻿") for c in r] for r in csv.reader(f, delimiter="\t")]


def _col(header: List[str], *substrs: str) -> Optional[int]:
    for i, h in enumerate(header):
        hl = _norm(h)
        if all(s in hl for s in substrs):
            return i
    return None


def _act_url(today: dt.date) -> str:
    """URL for the per-rep ACTIVATIONS worksheet: pin the completed week via
    'Activation Date Week Ending (copy)' = that week's Saturday in ISO. Without
    it the dashboard shows the in-progress week (Carlos 62, not 808)."""
    sat = P.cycle_saturday(today).isoformat()
    return f"{VIEW}?:iid=1&{WEEK_FIELD}={sat}"


def _rates_url(today: dt.date) -> str:
    """URL for the RATE worksheets (Captain Team Check 2/4, CB-Owner Metrics).
    These are rolling 0-30 / 31-60 day cohort metrics — the dashboard DEFAULT
    view gives the correct current rates (Carlos 4.2% / 78.2% / 2.58% / 4.4%).
    Pinning the activation-week filter degenerates them (1.0% / 100.0% / blank),
    so we deliberately do NOT apply it here."""
    return f"{VIEW}?:iid=1"


def parse_activations(path: Path) -> Dict[str, int]:
    """CB-Owner Sales -> {owner lower: activations} for Carlos' team."""
    rows = _read(path)
    reps: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) >= 3 and _norm(r[0]) == TEAM and _norm(r[1]):
            reps[_norm(r[1])] = _parse_int(r[2])
    return reps


def parse_roster(path: Path) -> set:
    """CB-Owner Metrics -> set of Carlos' team owner names (lower). This is the
    SFDC team membership (every current member, incl a 0-activation week), so
    it drives who to keep vs hide — NOT the activation list."""
    rows = _read(path)
    return {_norm(r[1]) for r in rows[1:]
            if len(r) > 1 and _norm(r[0]) == TEAM and _norm(r[1])}


def _team_row(path: Path):
    rows = _read(path)
    header = rows[0]
    row = next((r for r in rows[1:] if r and _norm(r[0]) == TEAM), None)
    return header, row


def _owner_row(path: Path, owner: str):
    rows = _read(path)
    header = rows[0]
    row = next((r for r in rows[1:]
                if len(r) > 1 and _norm(r[0]) == TEAM and _norm(r[1]) == owner), None)
    return header, row


def _pull(today, scratch, verbose, use_cache):
    scratch.mkdir(parents=True, exist_ok=True)
    files = {
        "sales": scratch / "cb_owner_sales.csv",
        "check2": scratch / "captain_team_check_2.csv",
        "check4": scratch / "captain_team_check_4.csv",
        "metrics": scratch / "cb_owner_metrics.csv",
    }
    # per-rep activations need the pinned completed week; the rate worksheets
    # need the DEFAULT view (pinning the week breaks their cohort math).
    jobs = [
        ("sales", "CB-Owner Sales", _act_url(today)),
        ("check2", "Captain Team Check (2)", _rates_url(today)),
        ("check4", "Captain Team Check (4)", _rates_url(today)),
        ("metrics", "CB-Owner Metrics", _rates_url(today)),
    ]
    if not use_cache:
        if verbose:
            print(f"  CaptainsTeam week ending (Sat) {P.cycle_saturday(today)} "
                  f"(sheet WE {P.cycle_sunday(today)})", flush=True)
        for key, sh, url in jobs:
            download_crosstab_patchright(url, sh, files[key], verbose=verbose)

    sales = parse_activations(files["sales"])
    roster = parse_roster(files["metrics"]) | set(sales)  # SFDC members ∪ any with activity
    reps = {n: sales.get(n, 0) for n in roster}            # 0-fill members with no activation
    grand = sum(reps.values())

    hdr2, row2 = _team_row(files["check2"])
    ci = _col(hdr2, "churn") or 1
    ai = _col(hdr2, "activation") or 2
    churn_team = row2[ci].strip() if row2 else None
    activation = row2[ai].strip() if row2 else None

    hdr4, row4 = _team_row(files["check4"])
    ni = _col(hdr4, "non", "pmt") or 1
    nonpmt = row4[ni].strip() if row4 else None

    hdrm, rowm = _owner_row(files["metrics"], CARLOS_OWNER)
    mci = _col(hdrm, "churn") or 2
    churn_personal = rowm[mci].strip() if rowm else None

    return CarlosPull(reps=reps, roster=roster, grand_total=grand,
                      churn_team=churn_team, churn_personal=churn_personal,
                      activation=activation, nonpmt=nonpmt)


def pull_carlos(today: dt.date, scratch_dir: Optional[Path] = None,
                verbose: bool = True) -> CarlosPull:
    return _pull(today, scratch_dir or CACHE_DIR, verbose, use_cache=False)


def parse_cached(scratch_dir: Optional[Path] = None) -> CarlosPull:
    return _pull(dt.date.today(), scratch_dir or CACHE_DIR, False, use_cache=True)
