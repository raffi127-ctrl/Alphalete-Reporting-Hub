"""Data-needs for the alphalete_org_report OPT family (SHADOW, Phase-1 cache-read).

Nothing on the live path imports this. Extends the harvest cache to the OPT
reports (nds / b2b / box / je / retail). Phase-1 ONLY: harvest each view once and
serve it back byte-identically — NO org-wide slicing / recompute for this family
(not worth the correctness risk; the win here is killing redundant logins).

Identity notes (why these are declared this way):
  * SAVED_VIEW pulls: filters baked in the view GUID → filters={} , the URL is
    the identity.
  * URL_PARAMS pulls (SARA / ABP / retail-by-club / JE sales): date-pinned to the
    target Mon–Sun week. Keyed on (BASE url WITHOUT the date params) + canonical
    filters {"Min Date","Max Date"} + pull_mode, so the key is stable regardless
    of how each module assembles the query string. Dates come from the report's
    OWN helper so they match by construction.
  * HTTP pulls (tableau_http .csv) and the retail SARA View-Data SCRAPE use
    distinct pull_mode values ("http" / "scrape") so they never collide with a
    crosstab pull of the same workbook.

Reuses the report modules' real constants + date helper — nothing transcribed.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.harvest.needs import DataNeed, dedupe_by_cache_key


def week_filters(target: dt.date | None = None) -> Dict[str, str]:
    """The report's OWN Mon–Sun window for `target` — identical dict the OPT
    modules pin SARA/ABP/by-club to (`_target_week_date_range`)."""
    from automations.alphalete_org_report.opt_nds import _target_week_date_range
    return _target_week_date_range(target)


def org_report_needs(target: dt.date | None = None) -> List[DataNeed]:
    """All Tableau (only) DataNeeds for the OPT family on `target`. opt_frontier
    is email/PDF-sourced → excluded."""
    target = target or dt.date.today()
    wk = week_filters(target)

    from automations.alphalete_org_report import opt_nds, opt_box
    from automations.recruiting_report import opt_phase_carlos as cb

    ORG_DD = DataNeed("DirectDeposit/ORG", opt_nds.ORG_DD_URL, opt_nds.ORG_DD_SHEET,
                      label="Org Direct Deposit (shared 5×)")

    needs: List[DataNeed] = [
        # ---- shared across ALL campaigns (pulled 5× today → 1) ----
        ORG_DD,

        # ---- NDS UI crosstabs (opt_nds NDS_VIEWS) ----
        DataNeed("NDS/DailyTracker", "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1", "TT-LineN/P Detail", label="NDS TT detail"),
        DataNeed("NDS/DailyTracker", "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1", "Rep Summary", label="NDS rep summary"),
        DataNeed("NDS/CHURNRATES", "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/c289786d-e0d4-4de7-825a-264c21e133c1/THISWEEK?:iid=1", "Churn Rates (ICD)", label="NDS churn (THISWEEK)"),
        DataNeed("NDS/ProductSalesSummaryRep", "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/5e31de75-1d1c-4f23-b234-4148516134c0/Thisweekandlast?:iid=1", "Sales By ICD (Weekly View)", label="NDS personal production"),
        # date-pinned crosstabs (url_params)
        DataNeed("DropshipV_2/SARAPLUSSALESSUMMARY", "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/SARAPLUSSALESSUMMARY?:iid=1", "Sara Plus Sales Summary", filters=wk, pull_mode="url_params", label="NDS SARA plus (crosstab)"),
        DataNeed("DropshipV_2/ABPCONVERSIONS", "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/ABPCONVERSIONS?:iid=1", "ABP National Average (2)", filters=wk, pull_mode="url_params", label="NDS ABP"),

        # ---- NDS HTTP pulls (tableau_http .csv) ----
        DataNeed("DropshipV_2/ACTIVATIONRATES", "DropshipV_2/ACTIVATIONRATES", "", pull_mode="http", label="NDS activation (http)"),
        DataNeed("NDS/NDSWeeklyMetricsRep", "NDS-SNRES-ATT-OOFWorkbook/NDSWeeklyMetricsRep", "", pull_mode="http", label="NDS weekly metrics (http)"),
        DataNeed("NDS/LeadPenetrationOverview", "NDS-SNRES-ATT-OOFWorkbook/LeadPenetrationOverview", "", pull_mode="http", label="NDS lead penetration (http)"),
        DataNeed("DropshipV_2/SARAPLUSSALESSUMMARYBYDAY", "DropshipV_2/SARAPLUSSALESSUMMARYBYDAY", "", filters=wk, pull_mode="http", label="NDS SARA byday (http)"),

        # ---- Box ----
        DataNeed("B2BBOXEnergyTracker", opt_box.BOX_TRACKER_URL, opt_box.BOX_WTD_SHEET, label="Box sales metrics"),
    ]

    # ---- B2B ----
    from automations.alphalete_org_report import opt_b2b
    needs.append(DataNeed("ATTTRACKER-B2B/B2BATTSalesMetrics", opt_b2b.B2B_PP_URL,
                          opt_b2b.B2B_PP_SHEET, label="B2B personal production"))
    # carlos saved-view set opt_b2b actually pulls (skips 'dd' + 'personal_production').
    # NB: 'churn' == ALLTEAMCHURN → same cache_key as the churn cluster's need
    # (cross-report dedup, collapsed below).
    _WANT = {"d2d1", "cancel", "activation", "churn", "penetration"}
    for vc in cb.VIEWS:
        if vc.key in _WANT:
            needs.append(DataNeed(f"B2B/{vc.key}", vc.url, vc.sheet_thumbnail_match,
                                  label=f"B2B {vc.key}"))

    # TODO(next): opt_je (per-ICD _je_sales_url + conversion + DD) and opt_retail
    # (by-club/SARA-scrape/ABP url_params + money-lost + churn/activation http).
    # Both use dynamic URL builders — wire via their builder fns on `target`.

    needs = [n for n in needs if n.view_url]
    return dedupe_by_cache_key(needs)
