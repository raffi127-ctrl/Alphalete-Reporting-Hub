"""Tableau pull for the per-captain workbook — ONE session per run.

Reuses Rafael's extractors + URL templates verbatim (automations.fiber_activations.pull),
just parametrized per captain. A single run gathers:

  COUNTRY (global, written into all 5 tabs' orange table):
    - country activations = sum of EVERY team's 'CB Activations (<team>)' Grand
      Total (auto-discovered, like Raf's report — the whole country, not just the
      5 captains).
    - country EOW sales  = PRODUCT SALES SUMMARY 4WK, all product types except
      UPGRADE INTERNET.

  PER CAPTAIN (violet table, one tab each):
    - activations  = that captain's 'CB Activations (<team>)' Grand Total
                     (REUSES the same crosstab already pulled for the country sum
                     — no second download).
    - churn / appr = 'CB Appr + Churn (<team>)' Grand Total row.
    - EOW sales    = PSS filtered Captain's Bonus Teams v2 = "<team>'s Team".

Same single-fresh-session-per-download discipline as Raf's pull (sharing a
session silently breaks the Weekending filter on the 3rd+ call).
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from automations.fiber_activations import pull as P
from automations.fiber_activations import captains as C
from automations.shared.tableau_patchright import download_crosstab_patchright


@dataclass
class CaptainPull:
    team: str
    activations: int                 # Grand Total (today's running cumulative)
    per_day: Dict[str, int]
    churn: str                       # raw string e.g. "5.23%"
    appr: str                        # raw string e.g. "81.8%"
    eow: int                         # PSS Sales Total, "<team>'s Team" filtered


@dataclass
class CaptainsRunPull:
    captains: Dict[str, CaptainPull] = field(default_factory=dict)  # by team
    country_activations: int = 0     # sum of ALL discovered teams' Grand Totals
    country_per_day: Dict[str, int] = field(default_factory=dict)
    country_eow: int = 0             # PSS Sales Total minus UPGRADE INTERNET
    missing: list = field(default_factory=list)  # captains the dashboard lacked


def pull_run(today, scratch_dir: Optional[Path] = None,
             verbose: bool = False) -> CaptainsRunPull:
    scratch = scratch_dir or (Path(tempfile.gettempdir()) / "fiber_captains")
    scratch.mkdir(parents=True, exist_ok=True)

    url = P.build_cb_url(today)
    result = CaptainsRunPull()

    # --- COUNTRY activations: discover + sum every team (one CB Activations
    #     download per team, reused below for the per-captain violet). ---
    teams = P.discover_teams(url, verbose=verbose)
    if not teams:
        raise RuntimeError(
            "No 'CB Activations (<team>)' sheets in the Captain's Bonus Crosstab "
            "dialog — the view may have changed; can't pull activations.")

    team_act: Dict[str, P.TeamActivations] = {}
    for team in teams:
        out = scratch / f"cb_act_{team.lower().replace(' ', '_')}.csv"
        download_crosstab_patchright(url, f"CB Activations ({team})", out,
                                     verbose=verbose)
        team_act[team] = P._extract_team_activations(out, team)

    result.country_activations = sum(t.grand_total for t in team_act.values())
    per_day = {d: 0 for d in P.DAYS}
    for t in team_act.values():
        for d, v in t.per_day.items():
            per_day[d] = per_day.get(d, 0) + v
    result.country_per_day = per_day

    # --- COUNTRY EOW sales (PSS, all product types except UPGRADE INTERNET). ---
    we_sunday = P.cycle_sunday(today).isoformat()
    pss_base = P.PSS_VIEW_URL_TMPL.format(we_sunday=we_sunday)
    out = scratch / "pss_country.csv"
    download_crosstab_patchright(pss_base + P.PSS_PT_NO_UPGRADE, P.PSS_WORKSHEET,
                                 out, verbose=verbose)
    result.country_eow = P._extract_pss_sales_total(out, exclude_upgrade=False)

    # --- PER CAPTAIN: reuse activations crosstab; add churn/appr + EOW. ---
    for cap in C.CAPTAINS:
        ta = team_act.get(cap.team)
        if ta is None:
            # Captain has no section on the dashboard this run — flag, don't crash
            # (mirrors Raf's missing_teams behavior).
            result.missing.append(cap.team)
            continue

        out = scratch / f"cb_churn_{cap.team.lower()}.csv"
        download_crosstab_patchright(url, f"CB Appr + Churn ({cap.team})", out,
                                     verbose=verbose)
        churn, appr = P._extract_appr_churn(out)

        team_param = f"&Captain%27s%20Bonus%20Teams%20v2={cap.team}%27s%20Team"
        out = scratch / f"pss_{cap.team.lower()}.csv"
        download_crosstab_patchright(pss_base + P.PSS_PT_ALL + team_param,
                                     P.PSS_WORKSHEET, out, verbose=verbose)
        eow = P._extract_pss_sales_total(out, exclude_upgrade=False)

        result.captains[cap.team] = CaptainPull(
            team=cap.team, activations=ta.grand_total, per_day=ta.per_day,
            churn=churn, appr=appr, eow=eow)

    return result
