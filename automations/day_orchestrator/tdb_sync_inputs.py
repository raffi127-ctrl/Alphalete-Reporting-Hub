"""Sync the Texas de Brazil dinner schedule from the git-tracked seed into the
run machine's local manual-inputs JSON, so a date typed on the Hub card (on any
machine) reaches the machine that actually runs the report (the mini).

Background: the Hub card writes dinner_schedule into
    ~/recruiting-report/output/texas_de_brazil_manual.json
which is MACHINE-LOCAL. Megan edits on the laptop; the report runs on the mini,
which reads its own copy — so the date never crossed over and the flyer showed
"TO BE DETERMINED". This helper bridges the gap by merging the committed seed
(deploy/texas_de_brazil_manual_inputs.json — synced via `lucy update`/git pull)
into that local JSON before the run.

SAFE MERGE: only writes the `dinner_schedule` key, and only for periods whose
seed entry has a non-empty day (never clobbers a locally-set date with a blank).
Every OTHER key in the local JSON (new_leaders_text, car_ride_text, anything
Maud/the report wrote) is preserved untouched — this never disturbs leaders.

Run standalone (from the 8AM wrapper):
    python -m automations.day_orchestrator.tdb_sync_inputs
or import and call sync() (from run_library_report).
"""
from __future__ import annotations

import json
from pathlib import Path

# Repo seed (git-tracked) and the report's machine-local manual-inputs file.
# LOCAL_INPUTS must match MANUAL_INPUTS in the report module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = _REPO_ROOT / "deploy" / "texas_de_brazil_manual_inputs.json"
LOCAL_INPUTS = Path.home() / "recruiting-report" / "output" / "texas_de_brazil_manual.json"


def sync(*, seed_file: Path = SEED_FILE, local_file: Path = LOCAL_INPUTS) -> dict:
    """Merge the seed's dinner_schedule into the local JSON. Best-effort:
    returns a small summary dict; never raises into a run (callers log it)."""
    try:
        seed = json.loads(seed_file.read_text())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"seed unreadable: {type(e).__name__}: {e}"}

    seed_sched = (seed.get("dinner_schedule") or {})
    # Only carry periods that actually have a date set — a blank seed entry must
    # not overwrite a date already present locally.
    incoming = {k: v for k, v in seed_sched.items()
                if str((v or {}).get("day", "")).strip()}
    if not incoming:
        return {"ok": True, "changed": [], "reason": "seed has no dated periods"}

    # Load existing local JSON (preserve every other key, e.g. leaders text).
    local = {}
    try:
        if local_file.exists():
            local = json.loads(local_file.read_text())
    except Exception:
        local = {}
    if not isinstance(local, dict):
        local = {}

    sched = dict(local.get("dinner_schedule") or {})
    changed = []
    for period, entry in incoming.items():
        if sched.get(period) != entry:
            changed.append(f"{period} = {entry.get('day')} / {entry.get('time')}")
        sched[period] = entry
    local["dinner_schedule"] = sched

    try:
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text(json.dumps(local, indent=2, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"local write failed: {type(e).__name__}: {e}"}

    return {"ok": True, "changed": changed, "local": str(local_file)}


def main() -> int:
    r = sync()
    if not r.get("ok"):
        print(f"[tdb_sync_inputs] skipped — {r.get('reason')}")
        return 0
    if r.get("changed"):
        print(f"[tdb_sync_inputs] synced dinner_schedule -> {r['local']}")
        for c in r["changed"]:
            print(f"[tdb_sync_inputs]   {c}")
    else:
        print(f"[tdb_sync_inputs] dinner_schedule already up to date ({r.get('reason','')})".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
