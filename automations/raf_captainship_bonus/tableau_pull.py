"""Pull Raf's team weekly bonus inputs from Tableau.

Source: ATTTRACKER2_1-D2D / CaptainsBonus (the "Captain Bonus" dashboard),
filtered to the current Wed-Tue cycle via the ``Weekending`` (Saturday) URL
param — the same view the Fiber Activations report already uses.

Two crosstabs:
  * ``CB Activations (Raf)``  — per-rep **Total Activations** (+ a Grand Total
    row) for Raf's Team. This is the per-rep number the Loom types in by hand.
  * ``CB Appr + Churn (Raf)`` — the team Grand Total's **60 Day New Internet
    Churn Rate** and **Rolling 4 Weeks** (= the sheet's New Internet
    Activation %).

Reuses the proven fiber_activations extractors + patchright ownerville SSO.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from automations.fiber_activations import pull as P
from automations.shared.tableau_patchright import download_crosstab_patchright

OWNER_COL = "ICD Owner Name"
TOTAL_COL = "Total Activations"
CACHE_DIR = Path("/tmp/raf_captainship_bonus")


@dataclass
class RafPull:
    reps: Dict[str, int] = field(default_factory=dict)  # {ICD name lower: Total Activations}
    grand_total: int = 0                                 # team Grand Total (sanity check)
    churn: Optional[str] = None                          # e.g. "6.07%"
    rolling: Optional[str] = None                        # e.g. "79.8%" (Activation %)

    @property
    def roster(self) -> set:
        """Current team membership = every rep CB Activations lists (it includes
        0-activation reps), so a slow week never drops someone from the roster."""
        return set(self.reps)


def _parse_int(s: str) -> int:
    s = (s or "").replace(",", "").strip()
    if s in ("", "-", "–", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def parse_activations(path: Path) -> tuple[Dict[str, int], int]:
    """{ICD Owner Name (lower): Total Activations} for every Raf rep, plus the
    Grand Total row's Total Activations."""
    header, grand, cols = P._read_crosstab(path)
    if OWNER_COL not in cols or TOTAL_COL not in cols:
        raise RuntimeError(f"CB Activations (Raf) missing expected columns; "
                           f"header={header}")
    oi, ti = cols[OWNER_COL], cols[TOTAL_COL]
    grand_total = _parse_int(grand[ti])
    reps: Dict[str, int] = {}
    with open(path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    for r in rows[2:]:                       # rows[0]=header, rows[1]=Grand Total
        if len(r) <= max(oi, ti):
            continue
        name = (r[oi] or "").strip()
        if not name or name.lower() == "total":
            continue
        reps[name.lower()] = _parse_int(r[ti])
    return reps, grand_total


def pull_raf(today: dt.date, scratch_dir: Optional[Path] = None,
             verbose: bool = True) -> RafPull:
    scratch = scratch_dir or CACHE_DIR
    scratch.mkdir(parents=True, exist_ok=True)
    url = P.build_cb_url(today)
    if verbose:
        print(f"  CaptainsBonus Weekending={P.cycle_saturday(today)} "
              f"(WE Sunday {P.cycle_sunday(today)})", flush=True)

    act = scratch / "cb_act_raf.csv"
    download_crosstab_patchright(url, "CB Activations (Raf)", act, verbose=verbose)
    reps, grand = parse_activations(act)

    ac = scratch / "cb_apprchurn_raf.csv"
    download_crosstab_patchright(url, "CB Appr + Churn (Raf)", ac, verbose=verbose)
    churn, rolling = P._extract_appr_churn(ac)

    return RafPull(reps=reps, grand_total=grand, churn=churn, rolling=rolling)


def parse_cached(scratch_dir: Optional[Path] = None) -> RafPull:
    """Reuse already-downloaded CSVs (no live pull) — for --skip-download."""
    scratch = scratch_dir or CACHE_DIR
    reps, grand = parse_activations(scratch / "cb_act_raf.csv")
    churn, rolling = P._extract_appr_churn(scratch / "cb_apprchurn_raf.csv")
    return RafPull(reps=reps, grand_total=grand, churn=churn, rolling=rolling)
