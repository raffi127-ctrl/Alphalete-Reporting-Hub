"""Order-log ALLREPS harvest need (SHADOW — nothing on the live 4am path imports
this; only the harvest prime + proof do).

The 8 office-metrics reports (rashad / aya / cyrus / hammad / kash / salik / cody
/ haytham) each pull the IDENTICAL org-wide ALLREPS "A.Order Log" crosstab and
only diverge in a Python-side owner filter (_filter_crosstab_by_owner). So ONE
harvested pull serves all 8 byte-identically — priming it once replaces 8
redundant Tableau scrapes. daily_metrics is the exception (it pulls Raf's OWN
Custom View, a different GUID) and stays independent.

Why a SEPARATE module (not needs.py): needs.py is deliberately browser-free, and
order_log.py pulls in the patchright stack. This mirror lives here so only the
prime/proof (never the live path, never needs.py) touch the heavy import — same
pattern as needs_org_report.py.

Identity: the ALLREPS url carries the date window as URL params (Start/End Date).
`cache_key`'s `_normalize_url` keeps those params, and both the prime AND the
runtime adapter build the url from order_log's OWN module constants
(ALLREPS_VIEW_URL_TMPL + START_DATE/END_DATE = last-month→yesterday, stable for
the calendar day), so the two cache_keys match by construction. Default
filters={} + pull_mode="saved_view" match what adapter.try_cache_view passes.
"""
from __future__ import annotations

import datetime as dt
from typing import List

from automations.harvest.needs import DataNeed


def order_log_needs(target: dt.date | None = None) -> List[DataNeed]:
    """The single ALLREPS "A.Order Log" DataNeed shared by the 8 office-metrics
    reports. `target` is accepted for signature parity with the other needs
    builders; order_log pins its own last-month→yesterday window from module
    constants (computed at import, stable for the day), so it isn't recomputed
    here — that keeps the key identical to what the runtime adapter builds."""
    from automations.uploaded import order_log as _ol

    url = _ol.ALLREPS_VIEW_URL_TMPL.format(start=_ol.START_DATE.isoformat(),
                                           end=_ol.END_DATE.isoformat())
    return [DataNeed(
        workbook="ATTTRACKER2_1-D2D/ORDERLOG",
        view_url=url,
        crosstab_sheet=_ol.CROSSTAB_SHEET,
        label="Order Log ALLREPS (shared by 8 office-metrics reports)",
    )]
