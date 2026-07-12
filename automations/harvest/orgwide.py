"""Phase-2: org-wide pull + Python slice (SHADOW-ONLY, INERT).

Nothing on the live 4am path imports this. See README.md.

The scaling lever (design §7): at 50-100 offices, N per-office saved views =
2*N Tableau pulls that can't dedup — that's what threatens the 8am deadline.
The fix is to pull ONE org-wide view and slice per office in Python.

The design flagged the one real hazard, which the Phase-2 probe CONFIRMED:
  * rep-level rows slice cleanly (org view is a byte-identical superset), BUT
  * the per-office **Grand-Total row does NOT survive** an org-wide collapse —
    the org file carries only the org-wide total. It must be RECOMPUTED from the
    sliced reps, and the recomputation must match Tableau's per-view Grand Total
    cell-for-cell (value AND %-format). `slice_b2b` does that; `proof_orgwide`
    proves it before anything trusts it.

Membership (which owners belong to a captainship) is a SEPARATE concern sourced
from the captainship roster in production; this module takes an explicit member
set so the proof can isolate the aggregation question from the membership one.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, Optional

# B2B churn period buckets (mirrors owners_metrics_churn.pull.B2B_PERIODS).
B2B_PERIODS = ("0-30", "30", "60", "90", "120")


def _fmt_pct(num: float, denom: float) -> Optional[str]:
    """Format a churn % the way Tableau's crosstab does: percentage to ONE
    decimal, round-half-up, trailing '%'. Returns None for an undefined ratio
    (denom == 0) — matches a blank Grand-Total cell."""
    if not denom:
        return None
    pct = (Decimal(str(num)) / Decimal(str(denom))) * Decimal(100)
    q = pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{q}%"


def recompute_office_total(reps: Dict[str, dict],
                           periods: Iterable[str] = B2B_PERIODS) -> dict:
    """Reconstruct a per-office Grand-Total row from its sliced rep rows:
    office num/denom per period = column sum of the reps' num/denom; pct =
    Tableau-formatted num/denom. Only emits a period any rep actually reports."""
    total: dict = {}
    for p in periods:
        present = [r[p] for r in reps.values() if p in r]
        if not present:
            continue
        num = sum(c["num"] for c in present if c.get("num") is not None)
        denom = sum(c["denom"] for c in present if c.get("denom") is not None)
        total[p] = {"num": num, "denom": denom, "pct": _fmt_pct(num, denom)}
    return total


def slice_b2b(org_parsed: dict, member_names: Iterable[str]) -> dict:
    """Slice an org-wide ALLTEAMCHURN parse_b2b payload down to one office.

    org_parsed: parse_b2b(ALLTEAMCHURN) — {"office_total": <ORG total>, "reps": {..all..}}
    member_names: the office's owner rows (from the roster in production; from the
                  per-view control in the proof).

    Returns a payload shaped exactly like a per-view parse_b2b result:
      * reps: only this office's rows (taken verbatim from the org pull), and
      * office_total: RECOMPUTED from those rows (the org-wide total is dropped).
    Also reports which requested members were missing from the org pull.
    """
    members = list(member_names)
    org_reps = org_parsed.get("reps", {})
    reps = {name: org_reps[name] for name in members if name in org_reps}
    missing = [name for name in members if name not in org_reps]
    return {
        "office_total": recompute_office_total(reps),
        "reps": reps,
        "_missing_members": missing,   # non-empty => roster/team drift to flag
    }
