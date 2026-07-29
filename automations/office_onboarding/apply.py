"""Materialize onboarding submissions into the report wiring.

The form (app.py) writes each office's config to the 'Office Onboarding' tab —
the source of truth. This step reads that tab and turns it into the two things a
new office actually needs to run:

  1. a row in the family registry  (office_metrics or b2b_metrics), written to a
     COMMITTED `onboarded_offices.json` that offices.py merges at import — so the
     Hub card, the runner, and Pay Structure all pick the office up with no
     hand-editing (they already read OFFICES).
  2. a `<key>_metrics` entry in day_orchestrator/schedule_config.json, assigned
     to the machine the office's view owners imply (Lucy 1 / Lucy 2).

DRY-RUN by default — prints exactly what would change and runs the family's own
validate() so a duplicate channel/view/key is refused BEFORE anything is written.
`--write` applies it. Nothing is committed or pushed here; Megan reviews the git
diff and commits (repo is public — see CLAUDE.md).

  python -m automations.office_onboarding.apply              # show the plan
  python -m automations.office_onboarding.apply --write      # write JSON + schedule
  python -m automations.office_onboarding.apply --only cyrus # one office
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from automations.office_onboarding import store
from automations.office_onboarding.schema import (
    OnboardingRecord, REPORTS_BY_KEY, validate)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_CONFIG = REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"
ONBOARDED_JSON = {
    "d2d": REPO_ROOT / "automations" / "office_metrics" / "onboarded_offices.json",
    "b2b": REPO_ROOT / "automations" / "b2b_metrics" / "onboarded_offices.json",
}


def _office_row(rec: OnboardingRecord) -> dict:
    """The registry row for this office, in the family's Office(...) field shape.
    Per-office view URLs are included only when the office enrolled a real one
    (shared-view reports leave them empty, matching the pure-config offices)."""
    views = {er.key: er.view_url.strip()
             for er in rec.enrolled_views()}
    row = {
        "key": rec.key,
        "report_id": rec.report_id(),
        "label": rec.display_label(),
        "owner": rec.owner,
        "channel_id": rec.channel_id,
        "channel_name": rec.channel_name,
        "sheet_id": rec.sheet_id,
        "knocks_office": rec.knocks_office,
        "ov_account": rec.ov_account,
        "owner_office": rec.owner_office,   # B2B "Owner & Office" slice value
        "business_name": rec.business_name,
        "website": rec.website,
        "header_label": rec.header_label,
        "thresholds": rec.thresholds,   # universal house standard (not per-office)
        "enrolled_reports": [er.key for er in rec.ordered_reports()],  # thread order
        "report_order": {er.key: er.order for er in rec.ordered_reports()},
        "per_office_views": views,      # {report_key: url} — usually empty
        "machine": rec.machine(),
        "notes": rec.notes,
    }
    # Per-channel fan-out plans (channel + its metric subset). The runner only
    # fans out when EVERY plan carries a resolved channel_id (set on finalize);
    # otherwise it posts everything to the primary channel. Carry them through so
    # the office_metrics/b2b_metrics merge can enable the fan-out.
    if rec.channel_plans:
        row["channel_plans"] = [
            {"channel_id": p.channel_id, "channel_name": p.channel_name,
             "report_keys": list(p.report_keys), "header_label": ""}
            for p in rec.channel_plans]
    # D2D offices are set up by DUPLICATING the "Master Metrics Templates"
    # workbook (Megan 2026-07-28), whose churn/ABP tabs are named on the
    # "Lucy ..." convention — not the older "Local Office - ..." names the fills
    # default to. Carry those labels so the runner writes to the tabs that
    # actually exist (office_metrics.runner passes them as CHURN_NI_TAB /
    # CHURN_WL_TAB / ABP_TAB). B2B has its own tab handling, so scope to D2D.
    if rec.family == "d2d":
        row["churn_ni_tab"] = "Lucy New INT Churn"
        row["churn_wl_tab"] = "Lucy Wireless Churn"
        row["abp_tab"] = "Lucy New INT ABP%"
    return row


def _schedule_entry(rec: OnboardingRecord, order_hint: float) -> dict:
    """A schedule_config.json report entry mirroring cyrus_metrics: runs the
    family runner for this office, machine-assigned, P1 daily, manifest-verified."""
    entry = {
        "order": order_hint,
        "on_scheduler": True,
        "display_name": f"{rec.display_label().split(chr(39))[0]}'s "
                        f"{'B2B' if rec.family == 'b2b' else 'Daily'} Metrics "
                        f"({rec.channel_name})",
        "source_type": "tableau",
        "data_sources": ["tableau:order_log"],
        "command": [rec.runner_module()],
        "base_args": ["--office", rec.key, "--live"],
        "cadence": {"weekdays": [0, 1, 2, 3, 4, 5, 6]},
        "priority": "P1",
        "freshness_target": None,
        "depends_on": [],
        "timeout_minutes": 60,
        "verify": {"type": "manifest", "report_id": rec.report_id()},
        "_note": (f"Office metrics for {rec.key} -> {rec.channel_name}. "
                  f"Onboarded via office_onboarding on {rec.submitted_at or '?'}. "
                  f"Machine {rec.machine()} (view owners)."),
        "_onboarded": True,
    }
    if rec.machine() != "Lucy 1":
        entry["machine"] = rec.machine()
    return entry


def plan() -> List[dict]:
    """Build per-office plans from the stored submissions."""
    out = []
    for d in store.load_all():
        rec = store.record_from_json(d)
        reg = store.existing_registry(exclude_key=rec.key)
        problems = validate(
            rec, existing_channels=reg["channels"],
            existing_keys=[k for k in reg["keys"] if k != rec.key],
            existing_views=reg["views"])
        out.append({"rec": rec, "problems": problems,
                    "row": _office_row(rec),
                    "family": rec.family})
    return out


def _merge_json(path: Path, rows: List[dict], write: bool) -> str:
    """Merge office rows into a family's onboarded_offices.json (keyed by 'key',
    last write wins). Returns a short human summary."""
    existing: Dict[str, dict] = {}
    if path.exists():
        try:
            existing = {r["key"]: r for r in json.loads(path.read_text())}
        except Exception:
            existing = {}
    added = [r["key"] for r in rows if r["key"] not in existing]
    updated = [r["key"] for r in rows if r["key"] in existing]
    for r in rows:
        existing[r["key"]] = r
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(existing.values()), indent=2))
        tmp.replace(path)
    return f"{path.relative_to(REPO_ROOT)}: +{added or '—'} ~{updated or '—'}"


def _patch_schedule(entries: Dict[str, dict], write: bool) -> str:
    raw = json.loads(SCHEDULE_CONFIG.read_text())
    reports = raw.setdefault("reports", {})
    added, updated = [], []
    for rid, entry in entries.items():
        (updated if rid in reports else added).append(rid)
        # preserve an existing explicit order if one was already tuned
        if rid in reports and reports[rid].get("order") is not None:
            entry["order"] = reports[rid]["order"]
        reports[rid] = {**reports.get(rid, {}), **entry}
    if write:
        tmp = SCHEDULE_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(SCHEDULE_CONFIG)
    return f"schedule_config.json: +{added or '—'} ~{updated or '—'}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_onboarding.apply")
    ap.add_argument("--write", action="store_true",
                    help="apply the changes (default: dry-run / show plan).")
    ap.add_argument("--only", default=None, help="materialize a single office key.")
    args = ap.parse_args(argv)

    plans = plan()
    if args.only:
        plans = [p for p in plans if p["rec"].key == args.only]
    if not plans:
        print("No onboarding submissions found (Office Onboarding tab / local "
              "fallback is empty).")
        return 0

    blocked = [p for p in plans if p["problems"]]
    if blocked:
        print("REFUSING to apply — these offices have problems:\n")
        for p in blocked:
            print(f"  ✗ {p['rec'].key}:")
            for pr in p["problems"]:
                print(f"      - {pr}")
        print("\nFix them in the form (resubmit) and re-run.")
        return 1

    by_family: Dict[str, List[dict]] = {}
    sched: Dict[str, dict] = {}
    order_base = 7.90
    for i, p in enumerate(plans):
        rec = p["rec"]
        by_family.setdefault(p["family"], []).append(p["row"])
        sched[rec.report_id()] = _schedule_entry(rec, order_base + i * 0.01)

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"=== office_onboarding.apply — {mode} — {len(plans)} office(s) ===\n")
    for p in plans:
        rec = p["rec"]
        print(f"  • {rec.key}: {rec.display_label()} -> {rec.channel_name} "
              f"[{rec.family.upper()} / {rec.machine()}]")
        vs = rec.enrolled_views()
        if vs:
            for er in vs:
                print(f"      view {er.key}: {er.view_machine} ({er.view_url[:60]}…)")
        else:
            print("      shared team views only (pure config)")
    print()
    for fam, rows in by_family.items():
        fam_key = "d2d" if fam == "d2d" else "b2b"
        print("  " + _merge_json(ONBOARDED_JSON[fam_key], rows, args.write))
    print("  " + _patch_schedule(sched, args.write))

    if not args.write:
        print("\nDRY-RUN — nothing written. Re-run with --write to apply, then "
              "review `git diff` and commit (nothing is auto-pushed).")
    else:
        print("\n✓ Written. NEXT: review `git diff`, run the office --dry-run on "
              "its machine to verify, then commit + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
