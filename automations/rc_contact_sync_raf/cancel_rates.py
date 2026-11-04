"""Per-rep ATT-fiber ongoing cancel rate for the wrap-up posts.

Reuses automations.ongoing_cancel (the "🔁 Ongoing Cancel" report every office's
metrics post already runs) pointed at the shared ALL-OFFICE AllExpanded view, so
ONE pull covers every rep across every office. The rate is the latest
running-sum day per rep, verbatim ('8.0%'), keyed by the title-cased rep name —
which comes from the same ATTTRACKER workbook as the Order Log, so it lines up
with the reps in the post.

Fails OPEN: any trouble pulling/parsing returns {} and the post simply omits the
cancel % rather than failing or guessing a number.
"""
from __future__ import annotations

import os
from typing import Dict

from automations.shared.name_case import titlecase_name


def fetch_map(log=print) -> Dict[str, str]:
    """{title-cased rep name: latest cancel-rate string}. {} on any failure."""
    try:
        from automations.office_metrics.offices import ALL_OFFICE_CANCEL_VIEW
        os.environ["ONGOING_CANCEL_VIEW_URL"] = ALL_OFFICE_CANCEL_VIEW
        os.environ.pop("ONGOING_CANCEL_SLICE_OWNER", None)   # want every rep
        from automations.ongoing_cancel import pull as ocp
        path = ocp.fetch_crosstab()
        parsed = ocp.parse(path, days=7)
        days = parsed.get("days", []) or []
        out: Dict[str, str] = {}
        for row in parsed.get("rows", []) or []:
            rep = titlecase_name(row.get("rep", ""))
            if not rep:
                continue
            per_day = row.get("per_day", {}) or {}
            # newest day (days is newest-first) that has a value
            rate = next((per_day[d][0] for d in days
                         if d in per_day and per_day[d] and per_day[d][0]), None)
            if rate:
                out[rep] = rate.strip()
        log("cancel rates: loaded %d rep(s) from the all-office view" % len(out))
        return out
    except Exception as e:                                 # noqa: BLE001
        log("cancel rates: could not load (%s: %s) — cancel %% omitted"
            % (type(e).__name__, str(e)[:160]))
        return {}
