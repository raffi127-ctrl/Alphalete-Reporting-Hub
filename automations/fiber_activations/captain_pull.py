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

LOGIN BUDGET (Megan 2026-08-17/18): this used to open a fresh Tableau login per
download — 20 a day, the worst report in the org. Now 8. The 13 CaptainsBonus
pulls (8 activations + 5 appr/churn) share ONE login, each on its own fresh
page; the 6 PSS pulls keep their own. PROVEN on the mini 2026-08-18 via
`lucy rerun session_proof_captainship` (A/B/A' hash diff, all 13 byte-identical:
output/logs/rerun-2026-08-18-120623-session_proof_captainship.log).

The old "fresh session per download" rule came from a real 2026-05-27 bug, but
it is NARROWER than it looked: it strikes repeat pulls of the SAME worksheet
differing only by URL query-param filters. The 13 differ by WORKSHEET NAME and
are safe. The 6 PSS pulls are all `Sales By ICD (Weekly View)` differing only by
a team/product param — exactly the leaking case — so they must NOT be folded in.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from automations.fiber_activations import pull as P
from automations.fiber_activations import captains as C
from automations.shared.tableau_patchright import (
    close_shared_session, download_crosstab_patchright, shared_page,
    tableau_session,
)


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

    # === PHASE 1 — every CaptainsBonus pull, ONE shared login ==================
    # Grouped deliberately: the shared context holds the Chrome profile, and a
    # tableau_session() opened while it is alive would collide on that same
    # profile ("already in use by another instance"). So ALL shared-session work
    # happens here, then the context is closed before any PSS pull. This is also
    # the exact order session_proof_captainship validated: 8 activations, then
    # the 5 appr/churn.
    team_act: Dict[str, P.TeamActivations] = {}
    for team in teams:
        out = scratch / f"cb_act_{team.lower().replace(' ', '_')}.csv"
        with shared_page(verbose=verbose) as pg:
            download_crosstab_patchright(url, f"CB Activations ({team})", out,
                                         verbose=verbose, page=pg)
        team_act[team] = P._extract_team_activations(out, team)

    result.country_activations = sum(t.grand_total for t in team_act.values())
    per_day = {d: 0 for d in P.DAYS}
    for t in team_act.values():
        for d, v in t.per_day.items():
            per_day[d] = per_day.get(d, 0) + v
    result.country_per_day = per_day

    churn_appr: Dict[str, tuple] = {}
    for cap in C.CAPTAINS:
        if team_act.get(cap.team) is None:
            # Captain has no section on the dashboard this run — flag, don't crash
            # (mirrors Raf's missing_teams behavior).
            result.missing.append(cap.team)
            continue
        out = scratch / f"cb_churn_{cap.team.lower()}.csv"
        with shared_page(verbose=verbose) as pg:
            download_crosstab_patchright(url, f"CB Appr + Churn ({cap.team})",
                                         out, verbose=verbose, page=pg)
        churn_appr[cap.team] = P._extract_appr_churn(out)

    close_shared_session()      # release the profile before any PSS pull

    # === PHASE 2 — PSS, a SEPARATE login each ================================
    # All of these hit the SAME worksheet and differ only by URL query-param
    # filters. Under one context the next pull inherits the previous filter and
    # returns a wrong number with NO error (proven on fiber 2026-08-17). Explicit
    # tableau_session() so the isolation holds regardless of what
    # TABLEAU_SHARED_SESSION is set to. Do NOT merge these into phase 1.
    we_sunday = P.cycle_sunday(today).isoformat()
    pss_base = P.PSS_VIEW_URL_TMPL.format(we_sunday=we_sunday)
    out = scratch / "pss_country.csv"
    with tableau_session(verbose=verbose) as pg:
        download_crosstab_patchright(pss_base + P.PSS_PT_NO_UPGRADE,
                                     P.PSS_WORKSHEET, out, verbose=verbose,
                                     page=pg)
    result.country_eow = P._extract_pss_sales_total(out, exclude_upgrade=False)

    for cap in C.CAPTAINS:
        ta = team_act.get(cap.team)
        if ta is None:
            continue                      # already flagged in result.missing
        team_param = f"&Captain%27s%20Bonus%20Teams%20v2={cap.team}%27s%20Team"
        out = scratch / f"pss_{cap.team.lower()}.csv"
        with tableau_session(verbose=verbose) as pg:
            download_crosstab_patchright(pss_base + P.PSS_PT_ALL + team_param,
                                         P.PSS_WORKSHEET, out, verbose=verbose,
                                         page=pg)
        eow = P._extract_pss_sales_total(out, exclude_upgrade=False)

        churn, appr = churn_appr[cap.team]
        result.captains[cap.team] = CaptainPull(
            team=cap.team, activations=ta.grand_total, per_day=ta.per_day,
            churn=churn, appr=appr, eow=eow)

    return result
