"""Materialize tracker-onboarding submissions into the tracker wiring.

The form writes each office to the 'Tracker Onboarding' tab. This reads that tab
and writes a COMMITTED onboarded_trackers.json that tableau_screenshots.slack_post
merges into ORG_CHANNELS / ORG_LABEL / ORG_TRACKERS at import — so the office's
channel joins the existing daily tracker run and appears on the Hub card with no
hand-edit. No schedule entry (one run already loops every org), no machine choice
(the boards are universal).

DRY-RUN by default; --write applies it. Nothing is committed/pushed — review the
git diff and commit.

  python -m automations.tracker_onboarding.apply            # show the plan
  python -m automations.tracker_onboarding.apply --write    # write onboarded_trackers.json
  python -m automations.tracker_onboarding.apply --only aeon
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from automations.tracker_onboarding import store
from automations.tracker_onboarding.schema import TrackerRecord, validate

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARDED_JSON = (REPO_ROOT / "automations" / "tableau_screenshots"
                  / "onboarded_trackers.json")


def _row(rec: TrackerRecord) -> dict:
    # channel_ids is already a LIST everywhere downstream (ORG_CHANNELS), so a
    # multi-channel enrollment just rides along — same boards to every channel.
    return {"key": rec.key, "label": rec.label(), "owner": rec.owner,
            "channel_ids": [cid for cid, _ in rec.channel_pairs()],
            "trackers": rec.trackers}


def plan() -> "List[dict]":
    out = []
    for d in store.load_all():
        rec = store.record_from_json(d)
        # Self-serve ICD requests sit as "pending" until Megan confirms them in
        # the form (status -> "wired"). A pending row must NEVER be materialized
        # — not even by a broad `apply --write` — or an unconfirmed channel
        # would start receiving posts.
        if rec.status == "pending":
            print(f"  (skipping {rec.key!r} — pending, not confirmed yet)")
            continue
        reg = store.existing_registry(exclude_key=rec.key)
        problems = validate(rec, existing_keys=[k for k in reg["keys"] if k != rec.key],
                            existing_channels=reg["channels"])
        out.append({"rec": rec, "problems": problems, "row": _row(rec)})
    return out


def _merge_json(rows: "List[dict]", write: bool) -> str:
    existing: Dict[str, dict] = {}
    if ONBOARDED_JSON.exists():
        try:
            existing = {r["key"]: r for r in json.loads(ONBOARDED_JSON.read_text())}
        except Exception:
            existing = {}
    added = [r["key"] for r in rows if r["key"] not in existing]
    updated = [r["key"] for r in rows if r["key"] in existing]
    for r in rows:
        existing[r["key"]] = r
    if write:
        ONBOARDED_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = ONBOARDED_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(existing.values()), indent=2))
        tmp.replace(ONBOARDED_JSON)
    return f"{ONBOARDED_JSON.relative_to(REPO_ROOT)}: +{added or '—'} ~{updated or '—'}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tracker_onboarding.apply")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)

    plans = plan()
    if args.only:
        plans = [p for p in plans if p["rec"].key == args.only]
    if not plans:
        print("No tracker-onboarding submissions found.")
        return 0

    blocked = [p for p in plans if p["problems"]]
    if blocked:
        print("REFUSING to apply — problems:\n")
        for p in blocked:
            print(f"  ✗ {p['rec'].key}:")
            for pr in p["problems"]:
                print(f"      - {pr}")
        return 1

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"=== tracker_onboarding.apply — {mode} — {len(plans)} office(s) ===\n")
    for p in plans:
        rec = p["rec"]
        print(f"  • {rec.key}: {rec.channel_name} — {len(rec.trackers)} trackers: "
              f"{', '.join(rec.trackers)}")
    print()
    print("  " + _merge_json([p["row"] for p in plans], args.write))
    if not args.write:
        print("\nDRY-RUN — nothing written. Re-run with --write, then review "
              "`git diff` and commit (the daily run + Hub card pick it up).")
    else:
        print("\n✓ Written. The next tableau_screenshots run posts to the new "
              "channel(s). Review `git diff`, then commit + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
