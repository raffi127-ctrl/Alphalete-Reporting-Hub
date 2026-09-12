"""Turn the harvest's raw addresses into a zone table the night send can use.

`harvest_zones.py` writes `output/icd_office_addresses.json` — one record per
ICD, with the city/state it read and the zone `addresses.resolve` derived. That
file is a SCRAPE LOG: it holds the failures too, and its shape is whatever the
harvester needed. This module reduces it to the one thing the sender asks for
("which zone is this ICD in?") and writes `output/icd_zones_harvested.json`,
which `zones.enable_harvested()` loads.

WHY A SECOND FILE INSTEAD OF READING THE FIRST ONE DIRECTLY. Because the two
answer to different people. The scrape log is evidence and is rewritten whole
by every harvest; the zone table is what a send acts on, and an ICD that was
resolved on Friday must not vanish from it because Saturday's harvest hit a
timeout on that one office. So this MERGES: a resolved ICD stays resolved until
a later harvest gives it a DIFFERENT zone, and a harvest that fails for an ICD
leaves the previous answer alone. That is also why the file keeps `first_seen`
— on Monday somebody wants to know which of these a machine decided and when.

NOTHING HERE EVER WRITES zones.ICD_TIMEZONES. Promoting an ICD into that table
is a person's job, and this file exists so they can do it from a list they can
read instead of from a scrape log.

    python -m automations.captainship_night_knocks.ingest
    python -m automations.captainship_night_knocks.ingest --print
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

from automations.captainship_night_knocks import addresses, zones as Z

IN_JSON = Path("output") / "icd_office_addresses.json"
OUT_JSON = Z.HARVESTED_JSON


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def reduce_records(records: Dict[str, dict]) -> Dict[str, dict]:
    """{icd: {zone, city, state, confidence, note}} for everything resolvable.

    Re-runs `addresses.resolve` rather than trusting the `zone` the harvester
    stored: the rule for split states lives in one place, and a record written
    by an older harvest must be read under TODAY's rule. Pure.
    """
    out: Dict[str, dict] = {}
    for icd, rec in (records or {}).items():
        city, state = (rec or {}).get("city"), (rec or {}).get("state")
        if not (city and state):
            continue
        r = addresses.resolve(city, state)
        if not r.zone:
            continue
        out[icd] = {"zone": r.zone, "city": city, "state": state,
                    "confidence": r.confidence, "note": r.note}
    return out


def unresolved(records: Dict[str, dict], resolved: Dict[str, dict]) -> Dict[str, str]:
    """{icd: why} for every harvested ICD that still has no zone. This is the
    list the sample email's footer prints: these ICDs are in nobody's wave."""
    out: Dict[str, str] = {}
    for icd, rec in (records or {}).items():
        if icd in resolved:
            continue
        rec = rec or {}
        if rec.get("city") and rec.get("state"):
            out[icd] = addresses.resolve(rec["city"], rec["state"]).note
        else:
            out[icd] = rec.get("note") or "no address read"
    return out


def merge(previous: dict, resolved: Dict[str, dict],
          stuck: Dict[str, str]) -> dict:
    """Fold a fresh harvest into whatever the last one left. See the docstring:
    a zone survives a harvest that could not re-read it. Pure."""
    prev_zones = dict((previous or {}).get("zones") or {})
    prev_meta = dict((previous or {}).get("detail") or {})
    zones_out = dict(prev_zones)
    detail = dict(prev_meta)
    for icd, r in resolved.items():
        zones_out[icd] = r["zone"]
        first = (prev_meta.get(icd) or {}).get("first_seen") or _now_iso()
        detail[icd] = dict(r, first_seen=first, last_seen=_now_iso())
    return {"harvested_at": _now_iso(), "zones": zones_out, "detail": detail,
            # Only the CURRENT harvest's failures: an ICD that resolved this
            # time must not keep appearing in the footer of every email.
            "unresolved": stuck}


def run(*, logfn=print) -> int:
    try:
        records = json.loads(IN_JSON.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logfn("[ingest] no harvest to read at %s (%s) — wrote nothing"
              % (IN_JSON, type(exc).__name__))
        return 1
    resolved = reduce_records(records)
    stuck = unresolved(records, resolved)
    try:
        previous = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — first run
        previous = {}
    payload = merge(previous, resolved, stuck)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True),
                        encoding="utf-8")
    logfn("[ingest] %d ICD(s) with a zone, %d still unplaced -> %s"
          % (len(payload["zones"]), len(stuck), OUT_JSON))
    return 0 if payload["zones"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", action="store_true",
                    help="show the current table and exit")
    args = ap.parse_args(argv)
    if args.print:
        n = Z.enable_harvested()
        print("[ingest] harvested layer: %d ICD(s) from %s"
              % (n, Z.harvested_source()))
        try:
            data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("[ingest] nothing to print (%s)" % type(exc).__name__)
            return 1
        for icd in sorted(data.get("zones") or {}):
            d = (data.get("detail") or {}).get(icd) or {}
            print("    %-28s %-30s %s, %s"
                  % (icd, data["zones"][icd], d.get("city"), d.get("state")))
        for icd, why in sorted((data.get("unresolved") or {}).items()):
            print("    ! %-26s %s" % (icd, why))
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
