"""Sync Texas de Brazil manual inputs (dinner date + backfill leaders) from the
shared LIVE store into the run machine's local manual-inputs JSON, so anything
typed on the Hub card (any machine) reaches the machine that runs the report.

Primary source: the 'TdB Manual Inputs' Sheet tab (tdb_manual_store) — a live
cross-machine store the Hub card writes and the mini reads. This is what lets
Maud add a backfill leader WITHOUT editing code (the edit-the-cell workflow is
what kept wiping the delivery layer). Fallback for the dinner date: the
git-tracked seed (deploy/texas_de_brazil_manual_inputs.json), in case the Sheet
is unreachable.

SAFE MERGE: only writes dinner_schedule / new_leaders_text / car_ride_text, and
only for the CURRENT competition period. Every other key in the local JSON is
preserved. The report also auto-detects leaders from the board on its own; the
manual text here is just backfill and de-dups against auto-detect at render time.

Run standalone (from the 8AM wrapper):  python -m automations.day_orchestrator.tdb_sync_inputs
or import and call sync() (from run_library_report).
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = _REPO_ROOT / "deploy" / "texas_de_brazil_manual_inputs.json"
LOCAL_INPUTS = Path.home() / "recruiting-report" / "output" / "texas_de_brazil_manual.json"


def _current_period() -> str:
    """Competition period 'YYYY-MM', anchored to yesterday (the last completed
    day) — matches the report module's own anchor so the 1st-of-month run still
    posts the prior month."""
    a = datetime.date.today() - datetime.timedelta(days=1)
    return f"{a.year}-{a.month:02d}"


def _load_local() -> dict:
    try:
        if LOCAL_INPUTS.exists():
            d = json.loads(LOCAL_INPUTS.read_text())
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def sync(*, period: str | None = None) -> dict:
    """Merge the current period's store row into the local JSON. Best-effort;
    returns a summary dict, never raises into a run."""
    period = period or _current_period()
    local = _load_local()
    changed = []

    # 1) Live Sheet store (primary) — dinner + backfill leaders.
    row = None
    try:
        from automations.day_orchestrator import tdb_manual_store as store
        row = store.get(period)
    except Exception as e:  # noqa: BLE001
        changed.append(f"(store unreachable: {type(e).__name__}: {e})")

    if row and row.get("exists"):
        day = str(row.get("dinner_day", "")).strip()
        if day:
            sched = dict(local.get("dinner_schedule") or {})
            entry = {"day": day, "time": str(row.get("dinner_time", "")).strip()}
            if sched.get(period) != entry:
                changed.append(f"dinner[{period}] = {entry['day']} / {entry['time']}")
            sched[period] = entry
            local["dinner_schedule"] = sched
        # Backfill leaders are AUTHORITATIVE for the period once a store row
        # exists (blank clears them; auto-detect still runs independently).
        for field, key in (("promotions", "new_leaders_text"), ("car_ride", "car_ride_text")):
            val = str(row.get(field, "") or "")
            if str(local.get(key, "") or "") != val:
                n = len([x for x in val.splitlines() if x.strip()])
                changed.append(f"{key} <- store ({n} line(s))")
            local[key] = val
    else:
        # 2) Fallback: git seed for the dinner date only (no store row yet).
        try:
            seed = json.loads(SEED_FILE.read_text())
            ent = (seed.get("dinner_schedule") or {}).get(period) or {}
            if str(ent.get("day", "")).strip():
                sched = dict(local.get("dinner_schedule") or {})
                if sched.get(period) != ent:
                    changed.append(f"dinner[{period}] = {ent.get('day')} / {ent.get('time')} (seed)")
                sched[period] = ent
                local["dinner_schedule"] = sched
        except Exception:
            pass

    try:
        LOCAL_INPUTS.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_INPUTS.write_text(json.dumps(local, indent=2, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"local write failed: {type(e).__name__}: {e}"}
    return {"ok": True, "period": period, "changed": changed, "local": str(LOCAL_INPUTS)}


def main() -> int:
    r = sync()
    if not r.get("ok"):
        print(f"[tdb_sync_inputs] skipped — {r.get('reason')}")
        return 0
    if r.get("changed"):
        print(f"[tdb_sync_inputs] synced {r['period']} -> {r['local']}")
        for c in r["changed"]:
            print(f"[tdb_sync_inputs]   {c}")
    else:
        print(f"[tdb_sync_inputs] {r['period']} already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
