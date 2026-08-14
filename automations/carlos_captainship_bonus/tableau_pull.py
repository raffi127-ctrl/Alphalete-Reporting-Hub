"""Pull Carlos' B2B team weekly bonus inputs from Tableau.

REBUILT 2026-08-13. The old source — ATTTRACKER-B2B / CaptainsTeam, custom view
"B2B Leader Recognition" — was deleted in a workbook republish, and its four
worksheets (CB-Owner Sales, Captain Team Check (2)/(4), CB-Owner Metrics) do not
exist anywhere in the workbook any more: the dashboard was rebuilt, not moved
(enumerated across every candidate view, 0/4 on each). So this is not a rename
— every number below comes from a different place now.

Both sources are BASE views, never saved custom views: those are per-user (the
bot signs in as Rafael) and die on every republish. Both are scoped with the
**team filter in the URL**, which is also what collapses the new rate views'
CRU/IRU split back into the single per-team row the old worksheets had.

  ACTIVATIONRATES / "Activation Office"  (team filter + week pinned)
      per-owner **weekly activations**. Each owner spans THREE rows
      (Activation % / Total Activations / Total Volume) x FOUR age buckets
      (0-7, 8-14, 15-30, 31-60 Days); the week's number is the
      "Total Activations" row SUMMED across the four buckets. The buckets are
      how long after the sale it activated -- not weeks -- so summing is
      required, not optional.

  B2B1-PAGER_CaptainView / "Churn, Activation and Tiers"  (team filter)
      Grand Total row -> team **Churn Rate (0-30)** + **Activation Rate
      (31-60)**; CARLOS HIDALGO's row -> his personal churn. Also the roster.

  B2B1-PAGER_CaptainView / "Captains View - Non pmt%"  (team filter)
      Grand Total row, "Grand Total" column -> team **Non Pmt %**.

Verified against WE 8.9 -- the last week that filled before the republish, whose
numbers are still in the sheet. Pulled 2 days later: activations Atef 221=221,
George 101=101, Gary 19=19, team 833 vs 827; churn team 3.8 vs 3.7; activation
76 vs 76.7; non-pmt 3.58 vs 3.48. The small drift is late-posted activations and
the rolling 0-30/31-60 cohorts moving on -- the report has always been a
Tuesday snapshot.

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
_SITE = "https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/"
# Where the per-owner activation COUNT lives. The rebuilt 1-pager views only
# publish SALES (team 1057 vs 827 activations for WE 8.9, and the ratio differs
# per owner, so it cannot be derived) -- this view is the only one carrying the
# count itself. [[project_carlos-captainship-bonus-view-dead]]
VIEW_ACTIVATIONS = _SITE + "ACTIVATIONRATES"
# Where the four rate/percentage cells come from.
VIEW_RATES = _SITE + "B2B1-PAGER_CaptainView"

WEEK_FIELD = "Activation%20Date%20Week%20Ending%20(copy)"  # value = Saturday ISO
# Scopes both views to Carlos' team. Same field captainship_drafts drives, and
# the reason the rate sheets return a single Grand Total row instead of a
# CRU + IRU pair. Proven live 2026-08-13 (70 rows -> 12).
TEAM_FIELD = "B2B Captain's Teams (SFDC)"
TEAM_VALUE = "Carlos's Team"

# Worksheet per role. Hoisted into ONE dict because a republish renames them as
# a set (2026-08-13 renamed all four at once) -- re-map here, not at scattered
# call sites. `probe_sheets.py` lists what each dialog currently offers and
# flags which of these went missing.
SHEETS = {
    "activations": "Activation Office",           # per-owner weekly activations
    "rates":       "Churn, Activation and Tiers",  # team + personal churn, activation
    "nonpmt":      "Captains View - Non pmt%",     # team Non Pmt %
}
CARLOS_OWNER = "carlos hidalgo"  # for the personal 0-30 churn
_GRAND_TOTAL = "grand total"
# The measure whose row carries the activation count on 'Activation Office'.
_ACT_MEASURE = "total activations"


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


def _team(url: str) -> str:
    """`url` scoped to Carlos' team. Both views need it: it is what limits the
    export to his owners AND what makes the rate sheets emit one Grand Total row
    instead of a CRU + IRU pair."""
    from urllib.parse import quote
    return f"{url}?{quote(TEAM_FIELD)}={quote(TEAM_VALUE)}&:iid=1"


def _act_url(today: dt.date) -> str:
    """URL for the ACTIVATIONS worksheet: team-scoped and pinned to the completed
    week via 'Activation Date Week Ending (copy)' = that week's Saturday in ISO.
    ISO ONLY — M/D/YYYY is ignored in silence and leaves the in-progress week
    (verified 2026-07-07). [[project_tableau-url-date-filter-iso]]"""
    sat = P.cycle_saturday(today).isoformat()
    return f"{_team(VIEW_ACTIVATIONS)}&{WEEK_FIELD}={sat}"


def _rates_url(today: dt.date) -> str:
    """URL for the RATE worksheets. These are rolling 0-30 / 31-60 day cohort
    metrics, so the view's own current state is the right answer — pinning the
    activation-week filter degenerates them (1.0% / 100.0% / blank), which is why
    the week is deliberately NOT applied here."""
    return _team(VIEW_RATES)


def _owner(cell: str) -> str:
    """'CARLOS HIDALGO\\r [alphalete specialized…]' -> 'carlos hidalgo'. The
    Activation Office member glues the office onto the name after an embedded CR
    (not LF), so splitting on newlines alone leaves the bracket attached."""
    head = str(cell or "").replace("\r", "\n").split("\n")[0]
    return _norm(head.split("[")[0])


def parse_activations(path: Path) -> Dict[str, int]:
    """Activation Office -> {owner lower: weekly activations}.

    Each owner spans three rows (Activation % / Total Activations / Total Volume)
    across four AGE buckets (0-7, 8-14, 15-30, 31-60 Days). We take the
    'Total Activations' row and SUM the buckets: they are how long after the sale
    it activated, not weeks, so any single bucket is a fraction of the week.
    """
    rows = _read(path)
    if not rows:
        return {}
    header = rows[0]
    # Bucket columns by HEADER ("0-7 Days", …), and the measure-name column as
    # the one actually holding 'Total Activations' — its header is blank, so it
    # can't be found by name. [[feedback_no_hardcoded_rows_or_columns]]
    buckets = [i for i, h in enumerate(header) if "days" in _norm(h)]
    measure = next(
        (i for i in range(len(header))
         if any(_norm(r[i]) == _ACT_MEASURE for r in rows[1:] if i < len(r))),
        None)
    if measure is None or not buckets:
        raise RuntimeError(
            f"'{SHEETS['activations']}' export has no {_ACT_MEASURE!r} row or no "
            f"bucket columns — header was {header!r}. The view changed again; "
            f"run probe_carlos_bonus_sheets.")
    reps: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) <= measure or _norm(r[measure]) != _ACT_MEASURE:
            continue
        name = _owner(r[0])
        if not name or name == _GRAND_TOTAL:
            continue
        reps[name] = sum(_parse_int(r[b]) for b in buckets if b < len(r))
    return reps


def parse_roster(path: Path) -> set:
    """Churn, Activation and Tiers -> Carlos' team owner names (lower). Every
    current member, including one who had a 0-activation week, so it drives who
    to keep vs hide — NOT the activation list."""
    rows = _read(path)
    if not rows:
        return set()
    oi = _col(rows[0], "icd owner name") or 0
    out = set()
    for r in rows[1:]:
        name = _owner(r[oi]) if len(r) > oi else ""
        if name and name != _GRAND_TOTAL:
            out.add(name)
    return out


def _rows_by_owner(path: Path):
    """(header, {owner lower: row}) for a sheet whose first column is the owner.
    'Grand Total' is kept under its own key — on the team-filtered rate sheets
    that row IS the team's number."""
    rows = _read(path)
    if not rows:
        return [], {}
    out = {}
    for r in rows[1:]:
        name = _owner(r[0]) if r else ""
        if name and name not in out:
            out[name] = r
    return rows[0], out


def _cell(header, row, *substrs) -> Optional[str]:
    i = _col(header, *substrs)
    if i is None or row is None or i >= len(row):
        return None
    return (row[i] or "").strip() or None


def _pull(today, scratch, verbose, use_cache):
    scratch.mkdir(parents=True, exist_ok=True)
    files = {
        "activations": scratch / "activation_office.csv",
        "rates": scratch / "churn_activation_tiers.csv",
        "nonpmt": scratch / "captains_non_pmt.csv",
    }
    # Activations need the pinned completed week AND a different view; the rate
    # sheets are rolling cohorts, so they take the view as it stands.
    jobs = [
        ("activations", SHEETS["activations"], _act_url(today)),
        ("rates", SHEETS["rates"], _rates_url(today)),
        ("nonpmt", SHEETS["nonpmt"], _rates_url(today)),
    ]
    if not use_cache:
        if verbose:
            print(f"  {TEAM_VALUE} · activations week ending (Sat) "
                  f"{P.cycle_saturday(today)} (sheet WE {P.cycle_sunday(today)})",
                  flush=True)
        for key, sh, url in jobs:
            download_crosstab_patchright(url, sh, files[key], verbose=verbose)

    sales = parse_activations(files["activations"])
    roster = parse_roster(files["rates"]) | set(sales)  # members ∪ any with activity
    reps = {n: sales.get(n, 0) for n in roster}          # 0-fill members with no activation
    grand = sum(reps.values())

    # Team churn + activation: the Grand Total row of the TEAM-FILTERED rate
    # sheet. Carlos' own row on the same sheet is his personal churn.
    hdr_r, by_owner = _rows_by_owner(files["rates"])
    total_row = by_owner.get(_GRAND_TOTAL)
    churn_team = _cell(hdr_r, total_row, "churn rate")
    activation = _cell(hdr_r, total_row, "activation rate")
    churn_personal = _cell(hdr_r, by_owner.get(CARLOS_OWNER), "churn rate")

    # Non Pmt %: same idea, and here the wanted number is the row's own
    # 'Grand Total' COLUMN (the per-product columns are the breakdown).
    hdr_n, by_team = _rows_by_owner(files["nonpmt"])
    nonpmt = _cell(hdr_n, by_team.get(_GRAND_TOTAL), "grand total")

    return CarlosPull(reps=reps, roster=roster, grand_total=grand,
                      churn_team=churn_team, churn_personal=churn_personal,
                      activation=activation, nonpmt=nonpmt)


def pull_carlos(today: dt.date, scratch_dir: Optional[Path] = None,
                verbose: bool = True) -> CarlosPull:
    return _pull(today, scratch_dir or CACHE_DIR, verbose, use_cache=False)


def probe_ready(today: dt.date, scratch_dir: Optional[Path] = None,
                verbose: bool = False) -> tuple[int, int]:
    """LIGHT readiness pull for the 4am orchestrator (Lucy 2): download ONLY the
    week-filtered **activations** crosstab and return (grand_total, n_reps).
    A 0-activation week still lists reps, so grand_total > 0 is the real signal
    that the just-ended week's activations are in the extract. One small
    crosstab; used by readiness._probe_captainship_bonus (fail-open at 10am)."""
    scratch = scratch_dir or CACHE_DIR
    scratch.mkdir(parents=True, exist_ok=True)
    out = scratch / "activation_office_probe.csv"
    download_crosstab_patchright(_act_url(today), SHEETS["activations"], out,
                                 verbose=verbose)
    reps = parse_activations(out)
    return sum(reps.values()), len(reps)


def parse_cached(scratch_dir: Optional[Path] = None) -> CarlosPull:
    return _pull(dt.date.today(), scratch_dir or CACHE_DIR, False, use_cache=True)
