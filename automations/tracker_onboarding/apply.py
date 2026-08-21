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


def _rows(rec: TrackerRecord) -> "List[dict]":
    """One onboarded_trackers.json row per DISTINCT board subset.

    No per-channel plans (or every plan identical) → the old single row, all
    channel_ids together. Differing subsets → one row PER channel (keys key,
    key2, key3 … — stable, [a-z0-9_] safe), each with only that channel's
    boards, ordered by the union order in rec.trackers. The poster loops org
    rows and captures each board once, so this costs nothing extra."""
    plans = [p for p in (rec.channel_plans or []) if p.get("channel_id")]
    order = {tid: i for i, tid in enumerate(rec.trackers)}

    def _ordered(tids: "List[str]") -> "List[str]":
        return sorted([t for t in tids if t in order], key=lambda t: order[t])

    same = (not plans or
            all(set(p.get("trackers") or []) == set(rec.trackers)
                for p in plans))
    if same:
        return [{"key": rec.key, "label": rec.label(), "owner": rec.owner,
                 "channel_ids": [cid for cid, _ in rec.channel_pairs()],
                 "trackers": rec.trackers}]
    out = []
    for i, p in enumerate(plans):
        out.append({
            "key": rec.key if i == 0 else f"{rec.key}{i + 1}",
            "label": p.get("channel_name") or rec.label(),
            "owner": rec.owner,
            "channel_ids": [p["channel_id"]],
            "trackers": _ordered(p.get("trackers") or []) or rec.trackers})
    return out


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
        out.append({"rec": rec, "problems": problems, "rows": _rows(rec)})
    return out


def _merge_json(recs_rows: "List[tuple]", write: bool) -> str:
    """Merge each office's row set, purging stale per-channel pseudo-rows
    (key2, key3, …) left behind when an office goes back to identical boards
    in every channel (or drops a channel)."""
    import re
    existing: Dict[str, dict] = {}
    if ONBOARDED_JSON.exists():
        try:
            existing = {r["key"]: r for r in json.loads(ONBOARDED_JSON.read_text())}
        except Exception:
            existing = {}
    added: List[str] = []
    updated: List[str] = []
    removed: List[str] = []
    for rec, rows in recs_rows:
        new_keys = {r["key"] for r in rows}
        for k in list(existing):
            if (k == rec.key
                    or re.fullmatch(re.escape(rec.key) + r"\d+", k)):
                if k not in new_keys:
                    removed.append(k)
                    del existing[k]
        for r in rows:
            (updated if r["key"] in existing else added).append(r["key"])
            existing[r["key"]] = r
    if write:
        ONBOARDED_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = ONBOARDED_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(existing.values()), indent=2))
        tmp.replace(ONBOARDED_JSON)
    return (f"{ONBOARDED_JSON.relative_to(REPO_ROOT)}: +{added or '—'} "
            f"~{updated or '—'} -{removed or '—'}")


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
        if len(p["rows"]) > 1:
            for r in p["rows"]:
                print(f"      {r['key']} -> {r['label']}: "
                      f"{', '.join(r['trackers'])}")
    print()
    print("  " + _merge_json([(p["rec"], p["rows"]) for p in plans], args.write))
    if not args.write:
        print("\nDRY-RUN — nothing written. Re-run with --write, then review "
              "`git diff` and commit (the daily run + Hub card pick it up).")
    else:
        print("\n✓ Written. The next tableau_screenshots run posts to the new "
              "channel(s). Review `git diff`, then commit + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
