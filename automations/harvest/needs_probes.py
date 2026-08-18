"""What the readiness PROBES pull, as DataNeeds — so proof_session can gate
`PROBE_SHARED_SESSION=1` (Megan 2026-08-18).

The access ledger's first full day put day_orchestrator at 16 Tableau logins,
spent entirely on asking "is the data there yet". Only THREE probes actually
download a crosstab on Lucy 1; 16 is those three re-probed across passes:

  dd_week               -> DDDETAILORG / "ORG DD Detail"
  box_daily             -> BoxDailyTracker / "Daily Tracker Sales"
  captainship_bonus_raf -> CaptainsBonus / "CB Activations (Raf)"

The other gates are cheaper than they look: tracker_att/nds/b2b go through
tableau_screenshots.freshness, which does NOT download a crosstab, and
att_orderlog runs on Lucy 2, so it never shares a pass with these.

All three differ by WORKSHEET, which the fiber + captainship proofs found safe
to share. Proving it anyway: a probe that inherits another's filter returns a
WRONG READINESS VERDICT, and a gate that wrongly says "ready" lets a report run
against a stale extract. Cheap to check — 3 pulls x 3 phases.

Built from each probe's OWN source (the box board's pinned_view_url, fiber's
build_cb_url, the dd probe's config block) so the URLs match what the probes
really request instead of being copied and left to drift.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import List, Optional

from automations.harvest.needs import DataNeed

CONFIG = Path(__file__).resolve().parents[2] / "automations" / "day_orchestrator" / "schedule_config.json"


def probe_needs(target: Optional[dt.date] = None) -> List[DataNeed]:
    today = target or dt.date.today()
    needs: List[DataNeed] = []

    cfg = json.loads(CONFIG.read_text())
    p = (cfg.get("sources", {}).get("tableau:dd_detail", {}) or {}).get("probe", {})
    if p.get("view_url") and p.get("crosstab_sheet"):
        needs.append(DataNeed(
            workbook="DirectDepositICDVIEWVersion2_0",
            view_url=p["view_url"], crosstab_sheet=p["crosstab_sheet"],
            label="probe - ORG DD Detail"))

    from automations.org_sales_board import section_pull as sp
    spec = sp.BOX_SPEC
    needs.append(DataNeed(
        workbook="B2BBOXEnergyTracker",
        view_url=sp.pinned_view_url(spec, today),
        crosstab_sheet=spec.crosstab_sheet,
        label="probe - Box daily tracker"))

    from automations.fiber_activations import pull as P
    needs.append(DataNeed(
        workbook="ATTTRACKER2_1-D2D/CaptainsBonus",
        view_url=P.build_cb_url(today),
        crosstab_sheet="CB Activations (Raf)",
        label="probe - CB Activations (Raf)"))

    return needs
