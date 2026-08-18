"""Wave harvest — pull each view WHEN THE ORCHESTRATOR SAYS IT IS READY, once,
so every report that wants it reads a file instead of signing in again.

Megan 2026-08-18. This replaces the shape of the old fixed pre-dawn harvest.
A single 2:30/3:00 job cannot work: the orchestrator's own probes say the data
does not exist yet at that hour (att_orderlog 05:30, trackers 06:30, box 08:00,
dd_detail 09:30, captainship_bonus 10:00), so it would defer nearly everything.
Earliness was never the point — pulling each view ONCE instead of N times is.
That works just as well at 09:30 as at 02:30.

HOW IT RIDES THE EXISTING GATE (and why it costs no probes):
`ReadinessCache` already probes each source and keeps a READY verdict sticky for
the day. The wave reads only that sticky set — `known_ready_sources()` — and
never probes anything itself. A source the orchestrator has not yet declared
ready is simply not harvested this pass; it gets picked up by a later wave once
the gate flips. So the wave adds ZERO readiness cost.

WHAT IT COSTS: one login per isolation group per wave (harvester._isolation_groups
keeps two needs that share a worksheet off the same login — the boundary the
session proofs established). Needs already in today's cache are skipped, so a
wave that has nothing new to do opens no session at all.

SCAFFOLDING, DEFAULT OFF (HARVEST_WAVE=1). Building it now against a PARTIAL
registry is deliberate (Megan's call): needs_for_report currently covers ~6 of
~59 scheduled tableau reports, because the ledger-generated registry needs a
full week of data before `from_ledger --days 7 --write` is honest. Until then a
wave harvests only what is declared, and every other report live-scrapes exactly
as it does today. Nothing regresses; the win just scales as the registry fills.

Reports only READ the cache when their own env sets HARVEST_MODE=on, so priming
here is inert until a report is cut over (one at a time, each with its own
proof).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import List, Optional

from automations.harvest.needs import DataNeed, dedupe_by_cache_key, needs_for_report


def wave_enabled() -> bool:
    return os.environ.get("HARVEST_WAVE", "").strip() in ("1", "on", "true")


def ready_needs(cache, todays, target_date: dt.date) -> List[DataNeed]:
    """Declared needs of today's tableau reports whose sources the orchestrator
    has ALREADY established are ready. Never probes — reads the sticky set only.

    A report with no data_sources declared is skipped rather than assumed ready:
    guessing here would harvest against an unrefreshed extract, and the loader
    would then serve that wrong-day file to anything cut over."""
    try:
        ready = cache.known_ready_sources()
    except Exception:                       # noqa: BLE001 — never break a pass
        return []
    out: List[DataNeed] = []
    for r in todays:
        if getattr(r, "source_type", None) != "tableau":
            continue
        srcs = list(getattr(r, "data_sources", None) or [])
        if not srcs or not all(s in ready for s in srcs):
            continue
        out.extend(needs_for_report(r.report_id))
    return dedupe_by_cache_key(out)


def _already_cached(need: DataNeed, target_date: dt.date) -> bool:
    """True when today's cache can already serve this need. Uses the loader, so
    'cached' means the same verified thing a report would get (right date,
    checksum ok, non-empty) — not merely that a file exists."""
    try:
        from automations.harvest.loader import load_harvest
        load_harvest(need, target_date)
        return True
    except Exception:                       # noqa: BLE001 — miss/stale => harvest it
        return False


def harvest_wave(cache, todays, target_date: dt.date, *,
                 logfn=print, cache_root: Optional[Path] = None):
    """Harvest everything newly-ready and not yet cached. Returns a HarvestResult
    or None when there was nothing to do (and no session was opened)."""
    if not wave_enabled():
        return None
    try:
        needs = [n for n in ready_needs(cache, todays, target_date)
                 if not _already_cached(n, target_date)]
    except Exception as e:                  # noqa: BLE001
        logfn(f"  [wave] need resolution failed ({type(e).__name__}: {e}) — skipping")
        return None
    if not needs:
        return None
    logfn(f"  [wave] {len(needs)} newly-ready need(s) to harvest")
    try:
        from automations.harvest.harvester import harvest
        # probe=False: the orchestrator's readiness gate already established
        # these sources are ready. Re-probing here would DOWNLOAD again, which is
        # the cost this whole exercise exists to remove.
        return harvest(target_date, needs, probe=False, logfn=logfn,
                       cache_root=cache_root)
    except Exception as e:                  # noqa: BLE001 — a prime must never fail a pass
        logfn(f"  [wave] harvest failed ({type(e).__name__}: {e}) — "
              f"reports fall back to their own pulls")
        return None
