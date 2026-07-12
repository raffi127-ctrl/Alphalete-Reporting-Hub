"""Phase-2 proof — org-wide slice == per-view pull, cell-for-cell (SHADOW-ONLY).

Nothing on the live 4am path imports this. Parse-only: no Sheet writes, no Slack.

The question this answers (design §7, deferred from the Phase-1 proof):
  Can we pull ONE org-wide B2B churn view (ALLTEAMCHURN) and reconstruct each
  captainship's per-view payload — INCLUDING the recomputed Grand-Total row —
  identically to pulling that captainship's own view?

    python -m automations.harvest.proof_orgwide              # harvest + diff
    python -m automations.harvest.proof_orgwide --no-harvest # re-diff from cache

Per office it reports three things separately:
  * membership : requested owners missing from the org pull (roster/team drift)
  * rep cells  : each owner row, org-slice vs per-view, cell-for-cell
  * GRAND TOTAL: recomputed office_total vs the per-view Tableau Grand Total
                 (the row the design warned a naive collapse breaks)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from automations.harvest.needs import (
    DataNeed, NEED_B2B_ALLTEAM, NEED_OWN_CARLOS, NEED_OWN_LUIS, NEED_OWN_EVELIZ,
)
from automations.harvest.harvester import harvest
from automations.harvest.loader import load_harvest
from automations.harvest.orgwide import slice_b2b
from automations.harvest.proof import _flatten, diff_payloads

# offices proven in this pass: (per-view need, human label)
OFFICES: List[Tuple[DataNeed, str]] = [
    (NEED_OWN_CARLOS, "Carlos"),
    (NEED_OWN_LUIS, "Luis"),
    (NEED_OWN_EVELIZ, "Eveliz"),
]


def _strip_meta(payload: dict) -> dict:
    """Drop bookkeeping keys (prefixed '_') so they don't enter the diff."""
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def run(target_date: dt.date, *, do_harvest: bool, logfn=print) -> dict:
    from automations.owners_metrics_churn import pull as omp

    needs = [NEED_B2B_ALLTEAM] + [n for n, _ in OFFICES]
    logfn(f"=== PHASE-2 PROOF {target_date.isoformat()} — org-wide slice vs per-view ===")
    logfn("side-effects: NONE (parse-only).\n")

    if do_harvest:
        from automations.shared.tableau_patchright import (
            tableau_session, download_crosstab_patchright)
        from contextlib import contextmanager

        @contextmanager
        def _keep(page):
            yield page
        logfn("--- Phase 1: harvest ALLTEAMCHURN + per-view offices (one login) ---")
        with tableau_session(verbose=False) as page:
            harvest(target_date, needs, probe=True, logfn=logfn,
                    _session_factory=lambda verbose=False: _keep(page),
                    _download=download_crosstab_patchright)
    else:
        logfn("--- (--no-harvest) re-diffing from existing cache ---")

    # Org-wide pull, parsed once (verified via the loader guard).
    org_parsed = omp.parse_b2b(load_harvest(NEED_B2B_ALLTEAM, target_date))
    logfn(f"\norg-wide ALLTEAMCHURN: {len(org_parsed['reps'])} owner rows, "
          f"org office_total periods={list(org_parsed['office_total'])}")

    results: List[dict] = []
    for need, name in OFFICES:
        logfn(f"\n===== {name} =====")
        control = omp.parse_b2b(load_harvest(need, target_date))     # per-view (truth)
        member_names = list(control["reps"].keys())
        treatment = slice_b2b(org_parsed, member_names)              # org slice + recompute

        # 1) membership fidelity
        missing = treatment["_missing_members"]
        logfn(f"  membership : {len(member_names)} owners; "
              + ("ALL present in org pull ✅" if not missing
                 else f"MISSING from org pull: {missing} ❌"))

        # 2) rep-cell fidelity (exclude office_total; that's checked separately)
        rep_diffs = diff_payloads(control["reps"], treatment["reps"])
        logfn(f"  rep cells  : {len(_flatten(control['reps']))} compared — "
              + ("identical ✅" if not rep_diffs else f"{len(rep_diffs)} MISMATCH ❌"))
        for d in rep_diffs[:10]:
            logfn(f"      {d}")

        # 3) GRAND TOTAL fidelity (the row the design warned about)
        gt_diffs = diff_payloads(control["office_total"], treatment["office_total"])
        logfn(f"  GRAND TOTAL: {len(_flatten(control['office_total']))} cells — "
              + ("recomputed == Tableau ✅" if not gt_diffs
                 else f"{len(gt_diffs)} MISMATCH ❌"))
        for d in gt_diffs:
            logfn(f"      {d}")

        office_ok = not missing and not rep_diffs and not gt_diffs
        results.append({
            "office": name, "members": len(member_names),
            "missing_members": missing,
            "rep_mismatches": rep_diffs, "grand_total_mismatches": gt_diffs,
            "identical": office_ok,
        })

    all_ok = all(r["identical"] for r in results)
    logfn("\n=== RESULT: "
          + ("org-wide slice REPRODUCES every per-view office cell-for-cell ✅"
             if all_ok else "MISMATCH — org-wide slice not yet trustworthy ❌")
          + " ===")
    return {"target_date": target_date.isoformat(), "all_identical": all_ok,
            "offices": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-proof-orgwide")
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--no-harvest", action="store_true",
                    help="skip the live pull; re-diff from an existing dated cache")
    args = ap.parse_args(argv)
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    summary = run(target, do_harvest=not args.no_harvest)
    return 0 if summary["all_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
