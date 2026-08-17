"""fiber_activations' pull spec, as DataNeeds — so proof_session can test the
report that logs in the most (Megan 2026-08-17).

fiber_activations/pull.py opens ONE Tableau login per crosstab (documented at
pull.py:254 as a deliberate workaround for a Weekending-filter bug). That makes
it the biggest single consumer of logins in the org:

    1  discover_teams (Crosstab-dialog enumeration)
    8  CB Activations (<team>)
    1  CB Appr + Churn (Raf)
    2  Product Sales Summary (country + Raf)
    --
    12 logins per run, every day

This module mirrors those pulls the same way needs_order_log.py mirrors the
order log: built from the report's OWN constants, so the URLs are identical by
construction rather than copied and left to drift. Browser-free import.

NOTE the 8 teams come from the module's TEAMS constant, not from a live
discover_teams() call — the proof must not spend a login just to build its own
list, and a team appearing/disappearing changes only which sheets get compared.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from automations.harvest.needs import DataNeed


def fiber_needs(target: Optional[dt.date] = None) -> List[DataNeed]:
    """The 11 crosstab pulls fiber_activations.pull_all makes, in run order.

    `target` drives the Weekending (Saturday) and WE Sunday URL filters exactly
    as pull_all does — pass the same date the report would use, or leave it
    None for today."""
    from automations.fiber_activations import pull as P

    today = target or dt.date.today()
    cb_url = P.build_cb_url(today)
    we_sunday = P.cycle_sunday(today).isoformat()
    pss_base = P.PSS_VIEW_URL_TMPL.format(we_sunday=we_sunday)

    needs: List[DataNeed] = []
    for team in P.TEAMS:
        needs.append(DataNeed(
            workbook="ATTTRACKER2_1-D2D/CaptainsBonus",
            view_url=cb_url,
            crosstab_sheet="CB Activations ({})".format(team),
            label="fiber — CB Activations ({})".format(team),
        ))
    needs.append(DataNeed(
        workbook="ATTTRACKER2_1-D2D/CaptainsBonus",
        view_url=cb_url,
        crosstab_sheet="CB Appr + Churn (Raf)",
        label="fiber — CB Appr + Churn (Raf)",
    ))
    needs.append(DataNeed(
        workbook="ProductSalesSummary",
        view_url=pss_base + P.PSS_PT_NO_UPGRADE,
        crosstab_sheet=P.PSS_WORKSHEET,
        label="fiber — PSS country (no upgrade)",
    ))
    needs.append(DataNeed(
        workbook="ProductSalesSummary",
        view_url=pss_base + P.PSS_PT_ALL + P.PSS_RAF_TEAM_PARAM,
        crosstab_sheet=P.PSS_WORKSHEET,
        label="fiber — PSS Raf",
    ))
    return needs
