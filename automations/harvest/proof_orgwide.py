"""Phase-2 proof — org-wide slice == per-view pull, cell-for-cell (SHADOW-ONLY).

Nothing on the live 4am path imports this. Parse-only: no Sheet writes, no Slack.

Proves, per workbook family, that pulling ONE org-wide churn view and slicing it
per office reproduces each office's per-view payload — INCLUDING the recomputed
office-total row the design warned a naive collapse breaks.

    python -m automations.harvest.proof_orgwide              # harvest + diff
    python -m automations.harvest.proof_orgwide --no-harvest # re-diff from cache

Families:
  * B2B  (ALLTEAMCHURN)      owner-keyed, 5 periods  -> slice_by_owner
  * NDS  (NDSAllTeamsChurn)  owner-keyed, 4 periods  -> slice_by_owner
  * D2D-NI (INTAllTeams)     column-keyed, 4 periods -> slice_d2d (by ICD Owner col)
  * D2D-WL (WirelessAllTeams) column-keyed, 4 periods -> slice_d2d
"""
from __future__ import annotations

import argparse
import csv as _csv
import datetime as dt
import sys
from pathlib import Path
from typing import List

from automations.harvest import needs as N
from automations.harvest.harvester import harvest
from automations.harvest.loader import load_harvest
from automations.harvest import orgwide as OW
from automations.harvest.proof import _flatten, diff_payloads


def _strip_color(reps: dict) -> dict:
    """Drop the parsed 'color' field — it is unused by the churn fill (colors are
    derived from pct via _pct_color_for), so it never reaches the sheet and must
    not enter a data diff."""
    return {name: {p: {k: v for k, v in slot.items() if k != "color"}
                   for p, slot in per.items()}
            for name, per in reps.items()}


def _family_table():
    """Lazily import the real report parsers and build the family table."""
    from automations.new_internet_churn import pull as nip
    from automations.captainship_churn import pull as cap
    from automations.owners_metrics_churn import pull as omp
    return [
        {"name": "D2D-NI-team", "org": N.NEED_D2D_NI_ALLTEAM, "parse": cap.parse,
         "kind": "team", "periods": OW.D2D_PERIODS, "decimals": 2,
         "title_fn": cap._smart_title,
         "offices": [(N.NEED_NI_CAP, "Raf captainship")]},
        {"name": "D2D-WL-team", "org": N.NEED_D2D_WL_ALLTEAM, "parse": cap.parse,
         "kind": "team", "periods": OW.D2D_PERIODS, "decimals": 2,
         "title_fn": cap._smart_title,
         "offices": [(N.NEED_WL_CAP, "Raf captainship")]},
        {"name": "B2B", "org": N.NEED_B2B_ALLTEAM, "parse": omp.parse_b2b,
         "kind": "owner", "periods": OW.B2B_PERIODS, "decimals": 1,
         "owner_col": "Owner & Office", "total_bare": {"Grand Total"},
         "offices": [(N.NEED_OWN_CARLOS, "Carlos"), (N.NEED_OWN_LUIS, "Luis")]},
        {"name": "NDS", "org": N.NEED_NDS_ALLTEAM, "parse": omp.parse_nds,
         "kind": "owner", "periods": OW.NDS_PERIODS, "decimals": 1,
         "owner_col": 0, "total_bare": {"Office/Organization Average"},
         "offices": [(N.NEED_OWN_KHALIL, "Khalil"), (N.NEED_OWN_COLTEN, "Colten")]},
        {"name": "D2D-NI", "org": N.NEED_D2D_NI_ALLTEAM, "parse": nip.parse,
         "kind": "column", "periods": OW.D2D_PERIODS, "decimals": 2,
         "offices": [(N.NEED_NI_LOCAL, "Raf office"), (N.NEED_NI_RASHAD, "Rashad")]},
        {"name": "D2D-WL", "org": N.NEED_D2D_WL_ALLTEAM, "parse": nip.parse,
         "kind": "column", "periods": OW.D2D_PERIODS, "decimals": 2,
         "offices": [(N.NEED_WL_LOCAL, "Raf office")]},
    ]


def _d2d_owner_value(control_path: Path) -> str:
    """Read the (constant) ICD Owner Name value from a per-view D2D crosstab."""
    with open(control_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    oi = header.index("ICD Owner Name (rep)")
    ri = header.index("Rep Name")
    for r in rows[1:]:
        if len(r) > max(oi, ri) and r[ri].strip() != "Total" and (r[oi] or "").strip():
            return r[oi].strip()
    return ""


def run(target_date: dt.date, *, do_harvest: bool, logfn=print) -> dict:
    fams = _family_table()
    logfn(f"=== PHASE-2 PROOF {target_date.isoformat()} — org-wide slice vs per-view ===")
    logfn("side-effects: NONE (parse-only).\n")

    if do_harvest:
        from contextlib import contextmanager
        from automations.shared.tableau_patchright import (
            tableau_session, download_crosstab_patchright)

        @contextmanager
        def _keep(page):
            yield page
        all_needs = []
        for fam in fams:
            all_needs.append(fam["org"])
            all_needs.extend(n for n, _ in fam["offices"])
        logfn(f"--- Phase 1: harvest {len(all_needs)} views (one login) ---")
        with tableau_session(verbose=False) as page:
            harvest(target_date, all_needs, probe=True, logfn=logfn,
                    _session_factory=lambda verbose=False: _keep(page),
                    _download=download_crosstab_patchright)
    else:
        logfn("--- (--no-harvest) re-diffing from existing cache ---")

    results: List[dict] = []
    for fam in fams:
        logfn(f"\n########## {fam['name']} ({fam['kind']}-keyed, "
              f"{len(fam['periods'])} periods, {fam['decimals']}-dec %) ##########")
        org_path = load_harvest(fam["org"], target_date)

        for need, label in fam["offices"]:
            logfn(f"\n===== {fam['name']} · {label} =====")
            control_path = load_harvest(need, target_date)
            control = fam["parse"](control_path)

            control_reps = control["reps"]
            if fam["kind"] == "owner":
                member_cells = OW.owner_cells(control_path, fam["owner_col"], fam["total_bare"])
                treatment = OW.slice_owner(org_path, member_cells, fam["parse"],
                                           owner_col=fam["owner_col"], periods=fam["periods"],
                                           decimals=fam["decimals"], total_bare=fam["total_bare"])
                missing = treatment["_missing_members"]
                logfn(f"  membership : {len(member_cells)} owner-cells; "
                      + ("all present ✅" if not missing else f"MISSING: {missing} ❌"))
            elif fam["kind"] == "team":
                members = set(control["reps"].keys())          # captainship's owners
                treatment = OW.slice_d2d_team(org_path, members, fam["title_fn"],
                                              periods=fam["periods"], decimals=fam["decimals"])
                missing = treatment["_missing_members"]
                # color is fill-derived from pct — exclude it from the data diff.
                control_reps = _strip_color(control["reps"])
                logfn(f"  membership : {len(members)} owners aggregated rep→owner; "
                      + ("all present ✅" if not missing else f"MISSING: {missing} ❌"))
            else:  # column-keyed D2D (per-office)
                owner_value = _d2d_owner_value(load_harvest(need, target_date))
                treatment = OW.slice_d2d(org_path, owner_value, fam["parse"],
                                         periods=fam["periods"], decimals=fam["decimals"])
                logfn(f"  slice key  : ICD Owner Name = {owner_value!r} → "
                      f"{treatment['_sliced_rows']} raw rows; "
                      f"{len(control['reps'])} reps in per-view")

            rep_diffs = diff_payloads(control_reps, treatment["reps"])
            logfn(f"  rep cells  : {len(_flatten(control_reps))} compared — "
                  + ("identical ✅" if not rep_diffs else f"{len(rep_diffs)} MISMATCH ❌"))
            for d in rep_diffs[:8]:
                logfn(f"      {d}")

            gt_diffs = diff_payloads(control["office_total"], treatment["office_total"])
            logfn(f"  OFFICE TOTAL: {len(_flatten(control['office_total']))} cells — "
                  + ("recomputed == Tableau ✅" if not gt_diffs
                     else f"{len(gt_diffs)} MISMATCH ❌"))
            for d in gt_diffs:
                logfn(f"      {d}")

            ok = not rep_diffs and not gt_diffs and not treatment.get("_missing_members")
            results.append({"family": fam["name"], "office": label,
                            "rep_mismatches": rep_diffs,
                            "office_total_mismatches": gt_diffs, "identical": ok})

    all_ok = all(r["identical"] for r in results)
    logfn("\n=== RESULT: " + (f"all {len(results)} offices REPRODUCED cell-for-cell ✅"
          if all_ok else "MISMATCH — see above ❌") + " ===")
    return {"target_date": target_date.isoformat(), "all_identical": all_ok,
            "offices": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-proof-orgwide")
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-harvest", action="store_true",
                    help="skip the live pull; re-diff from an existing dated cache")
    args = ap.parse_args(argv)
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    summary = run(target, do_harvest=not args.no_harvest)
    return 0 if summary["all_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
